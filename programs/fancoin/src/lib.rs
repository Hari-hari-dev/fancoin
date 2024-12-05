use anchor_lang::prelude::*;
//use anchor_lang::solana_program::keccak::hash;

use sha3::{Digest, Keccak256};
//use rand::Rng;
use chrono::{Utc, TimeZone, Timelike};
use std::convert::TryInto;

declare_id!("6GJQt9Rbz1BJBmKDPq9KgR2ThEtFtp47dJ9EnZ7Qdnhq");

const DECIMALS: u64 = 1_000_000_000; // 6 decimal places
#[allow(unexpected_cfgs)]

#[program]
pub mod fancoin {
    use super::*;

    pub fn initialize(ctx: Context<Initialize>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        dapp.owner = ctx.accounts.user.key();
        Ok(())
    }

    pub fn initialize_game(ctx: Context<InitializeGame>, game_number: u32, description: String) -> Result<()> {
        let game = &mut ctx.accounts.game;
        game.game_number = game_number;
        game.status = GameStatus::Probationary;
        game.description = description;
        game.validators = Vec::new();
        game.shards = Vec::new();
        game.token_balances = Vec::new();
        game.total_token_supply = 0;
        game.last_seed = None;
        game.last_punch_in_time = None;
        game.minting_agreements = Vec::new();
        Ok(())
    }

    pub fn update_game_status(ctx: Context<UpdateGameStatus>, game_number: u32, new_status: GameStatus, description: String) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let dapp = &ctx.accounts.dapp;
        let signer = &ctx.accounts.signer;

        // Only the owner can update the game status
        require!(dapp.owner == signer.key(), ErrorCode::Unauthorized);

        // Validate game_number
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Check if the status has already been set
        require!(game.status == GameStatus::Probationary, ErrorCode::GameStatusAlreadySet);

        // Update status and description
        game.status = new_status;
        game.description = description;

        Ok(())
    }


    pub fn punch_in(ctx: Context<PunchIn>, game_number: u32) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let validator = &mut ctx.accounts.validator;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
    
        // Validate game_number
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
    
        // Check if the game is blacklisted
        require!(game.status != GameStatus::Blacklisted, ErrorCode::GameIsBlacklisted);
    
        // Check if we are in the punch-in period
        require!(is_punch_in_period(current_time)?, ErrorCode::NotInPunchInPeriod);
    
        // Check stake
        let stake = get_stake(&game.token_balances, validator.key);
        require!(stake >= 32_000 * DECIMALS, ErrorCode::InsufficientStake);
    
        // Update validator's last activity or add new validator
        if let Some(existing_validator) = game.validators.iter_mut().find(|v| v.address == *validator.key) {
            existing_validator.last_activity = current_time;
        } else {
            game.validators.push(Validator {
                address: *validator.key,
                last_activity: current_time,
            });
        }
    
        // **Replace random seed generation with a deterministic hash**
    
        // Combine validator's public key and the current slot to generate a seed
        let seed_data = validator.key.to_bytes();
        let slot_bytes = clock.slot.to_le_bytes();
        let mut hasher = Keccak256::new();
        hasher.update(&seed_data);
        hasher.update(&slot_bytes);
        let hash_result = hasher.finalize();
    
        // Use the first 8 bytes of the hash as the seed
        let seed = u64::from_le_bytes(hash_result[0..8].try_into().unwrap());
    
        // Update the last seed and last punch-in time
        game.last_seed = Some(seed);
        game.last_punch_in_time = Some(current_time);
    
        Ok(())
    }

    pub fn register_player(ctx: Context<RegisterPlayer>, game_number: u32, name: String, reward_address: Pubkey) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let player_account = &mut ctx.accounts.player;
        let user = &ctx.accounts.user;

        // Validate game_number
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Check if the game is blacklisted
        require!(game.status != GameStatus::Blacklisted, ErrorCode::GameIsBlacklisted);

        // Check for name collision
        if game.shards.iter().any(|shard| {
            shard.players.iter().any(|&p_key| p_key == player_account.key())
        }) {
            return Err(ErrorCode::PlayerNameExists.into());
        }

        // Initialize player
        player_account.name = name.clone();
        player_account.address = user.key();
        player_account.reward_address = reward_address;
        player_account.last_minted = None;

        // Add player to a shard
        let shard_capacity = 100; // Adjust capacity as needed
        let mut added = false;
        for shard in &mut game.shards {
            if shard.players.len() < shard_capacity {
                shard.players.push(player_account.key());
                added = true;
                break;
            }
        }
        if !added {
            // Create new shard
            let new_shard = Shard {
                players: vec![player_account.key()],
            };
            game.shards.push(new_shard);
        }

        Ok(())
    }

    pub fn submit_minting_list(ctx: Context<SubmitMintingList>, game_number: u32, player_names: Vec<String>) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let validator = &ctx.accounts.validator;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        // Validate game_number
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Check if the game is whitelisted
        require!(game.status == GameStatus::Whitelisted, ErrorCode::GameNotWhitelisted);

        // Check if we are in the mint period
        require!(is_mint_period(current_time)?, ErrorCode::NotInMintPeriod);

        // Ensure validator is registered
        if !game.validators.iter().any(|v| v.address == *validator.key) {
            return Err(ErrorCode::ValidatorNotRegistered.into());
        }

        // Validate stake
        let stake = get_stake(&game.token_balances, validator.key);
        require!(stake >= 32_000 * DECIMALS, ErrorCode::InsufficientStake);

        // Process each player name
        for player_name in player_names {
            // Record validator's agreement to mint for this player
            if let Some(agreement) = game.minting_agreements.iter_mut().find(|ma| ma.player_name == player_name) {
                agreement.validators.push(*validator.key);
            } else {
                game.minting_agreements.push(MintingAgreement {
                    player_name: player_name.clone(),
                    validators: vec![*validator.key],
                });
            }
        }

        Ok(())
    }

    pub fn finalize_minting(ctx: Context<FinalizeMinting>, game_number: u32) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        // Validate game_number
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Check if the game is whitelisted
        require!(game.status == GameStatus::Whitelisted, ErrorCode::GameNotWhitelisted);

        // Check if we are in the mint period
        require!(is_mint_period(current_time)?, ErrorCode::NotInMintPeriod);

        let failover_tolerance = calculate_failover_tolerance(game.validators.len());

        let mut successful_mints = Vec::new();
        let mut validator_rewards = Vec::new();

        for agreement in &game.minting_agreements {
            // Check if at least two validators agree
            if agreement.validators.len() >= 2 {
                // Ensure validators are within failover group count of each other
                let first_validator = agreement.validators[0];

                let first_group_id = calculate_group_id(&first_validator, game.last_seed.unwrap())?;

                let mut validators_in_same_group = true;
                for validator in agreement.validators.iter().skip(1) {
                    let group_id = calculate_group_id(validator, game.last_seed.unwrap())?;
                    let group_distance = if group_id > first_group_id {
                        group_id - first_group_id
                    } else {
                        first_group_id - group_id
                    };
                    if group_distance > failover_tolerance as u64 {
                        validators_in_same_group = false;
                        break;
                    }
                }

                if validators_in_same_group {
                    // Add to successful mints
                    successful_mints.push(agreement.player_name.clone());

                    // Accumulate validator rewards
                    for validator in &agreement.validators {
                        if let Some(entry) = validator_rewards.iter_mut().find(|(vk, _)| vk == validator) {
                            entry.1 += 1_618_000_000 * DECIMALS / 1_000; // Adjusted for decimals
                        } else {
                            validator_rewards.push((*validator, 1_618_000_000 * DECIMALS / 1_000));
                        }
                    }
                }
            }
        }

        // Batch process successful mints
        for player_name in successful_mints {
            mint_tokens_for_player(game, &player_name, current_time)?;
        }

        // Batch update validator rewards
        for (validator_key, reward) in validator_rewards {
            mint_tokens(game, &validator_key, reward);
        }

        // Clear minting agreements after processing
        game.minting_agreements.clear();

        Ok(())
    }
}

// Define Context structs

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(init, payer = user, space = DApp::LEN, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct InitializeGame<'info> {
    #[account(init, payer = user, space = Game::LEN, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct UpdateGameStatus<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    #[account(seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
    #[account(mut)]
    pub signer: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct PunchIn<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    pub validator: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct RegisterPlayer<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    #[account(init, payer = user, space = Player::LEN)]
    pub player: Account<'info, Player>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct SubmitMintingList<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    pub validator: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct FinalizeMinting<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
}

// Define data structures

#[account]
pub struct DApp {
    pub owner: Pubkey,
}

impl DApp {
    pub const LEN: usize = 8 + // Discriminator
        32; // owner (Pubkey)
}

#[account]
pub struct Game {
    pub game_number: u32,
    pub status: GameStatus,
    pub description: String,
    pub validators: Vec<Validator>,
    pub shards: Vec<Shard>,
    pub token_balances: Vec<TokenBalance>,
    pub total_token_supply: u64,
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,
    pub minting_agreements: Vec<MintingAgreement>,
}

impl Game {
    pub const MAX_DESCRIPTION_LEN: usize = 256;
    pub const MAX_VALIDATORS: usize = 100;
    pub const MAX_SHARDS: usize = 10;
    pub const MAX_PLAYERS_PER_SHARD: usize = 100;
    pub const MAX_TOKEN_BALANCES: usize = 100;
    pub const MAX_MINTING_AGREEMENTS: usize = 100;

    pub const LEN: usize = 8 + // Discriminator
        4 + // game_number (u32)
        1 + // status (u8)
        4 + Self::MAX_DESCRIPTION_LEN + // description (String)
        (4 + Self::MAX_VALIDATORS * Validator::LEN) + // validators
        (4 + Self::MAX_SHARDS * Shard::LEN) + // shards
        (4 + Self::MAX_TOKEN_BALANCES * TokenBalance::LEN) + // token_balances
        8 + // total_token_supply (u64)
        9 + // last_seed (Option<u64>)
        9 + // last_punch_in_time (Option<i64>)
        (4 + Self::MAX_MINTING_AGREEMENTS * MintingAgreement::LEN); // minting_agreements
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, PartialEq, Eq)]
pub enum GameStatus {
    Probationary = 0,
    Whitelisted = 1,
    Blacklisted = 2,
}

impl Default for GameStatus {
    fn default() -> Self {
        GameStatus::Probationary
    }
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Validator {
    pub address: Pubkey,
    pub last_activity: i64, // Unix timestamp
}

impl Validator {
    pub const LEN: usize = 32 + 8; // Pubkey + i64
}

#[account]
pub struct Player {
    pub name: String,
    pub address: Pubkey,
    pub reward_address: Pubkey,
    pub last_minted: Option<i64>, // Unix timestamp
}

impl Player {
    pub const MAX_NAME_LEN: usize = 32;
    pub const LEN: usize = 
        4 + Self::MAX_NAME_LEN + // name (String)
        32 + // address (Pubkey)
        32 + // reward_address (Pubkey)
        9; // last_minted (Option<i64>)
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Shard {
    pub players: Vec<Pubkey>, // Store Pubkeys of Player accounts
}

impl Shard {
    pub const MAX_PLAYERS: usize = 100;
    pub const LEN: usize = 4 + (Self::MAX_PLAYERS * 32); // 4 bytes for vector length + Pubkeys
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct TokenBalance {
    pub address: Pubkey,
    pub balance: u64,
}

impl TokenBalance {
    pub const LEN: usize = 32 + 8; // Pubkey + u64
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct MintingAgreement {
    pub player_name: String,
    pub validators: Vec<Pubkey>,
}

impl MintingAgreement {
    pub const MAX_PLAYER_NAME_LEN: usize = 32;
    pub const MAX_VALIDATORS: usize = 100;
    pub const LEN: usize = 4 + Self::MAX_PLAYER_NAME_LEN + (4 + Self::MAX_VALIDATORS * 32); // Adjust accordingly
}

// Helper functions

fn is_punch_in_period(current_time: i64) -> Result<bool> {
    let datetime = match Utc.timestamp_opt(current_time, 0).single() {
        Some(dt) => dt,
        None => return Err(ErrorCode::InvalidTimestamp.into()),
    };
    let minute = datetime.minute();
    Ok((0..5).contains(&minute) || (20..25).contains(&minute) || (40..45).contains(&minute))
}

fn is_mint_period(current_time: i64) -> Result<bool> {
    Ok(!is_punch_in_period(current_time)?)
}

fn get_stake(token_balances: &Vec<TokenBalance>, address: &Pubkey) -> u64 {
    token_balances.iter()
        .find(|tb| &tb.address == address)
        .map(|tb| tb.balance)
        .unwrap_or(0)
}

fn calculate_failover_tolerance(total_validators: usize) -> usize {
    let total_groups = (total_validators + 3) / 4; // Round up
    let num_digits = total_groups.to_string().len();
    num_digits + 1
}

fn calculate_group_id(address: &Pubkey, seed: u64) -> Result<u64> {
    // Use Keccak256 hash function
    let mut hasher = Keccak256::new();
    hasher.update(address.to_bytes());
    hasher.update(&seed.to_le_bytes());
    let result = hasher.finalize();
    // Convert first 8 bytes to u64
    let hash_value = u64::from_be_bytes(result[0..8].try_into().map_err(|_| ErrorCode::HashConversionError)?);
    Ok(hash_value)
}

fn mint_tokens_for_player(game: &mut Account<Game>, player_name: &str, current_time: i64) -> Result<()> {
    // Placeholder: Load the player account from the context or use a mapping
    // In a real implementation, you would pass the player account in the context
    // For this example, we'll assume the player account is accessible

    // Placeholder player account
    let player_pubkey = Pubkey::default(); // Replace with actual lookup

    // Load player account (this requires passing it in the context)
    // For this simplified example, we proceed as if we have access

    // Placeholder logic
    let player = Player {
        name: player_name.to_string(),
        address: player_pubkey,
        reward_address: player_pubkey,
        last_minted: None,
    };

    let last_minted = player.last_minted.unwrap_or(current_time - 34 * 60); // Default to 34 minutes ago

    // Ensure at least 7 minutes have passed since the last mint
    let duration_since_last_mint = current_time - last_minted;
    if duration_since_last_mint < 7 * 60 {
        // Skip if not enough time has passed
        return Ok(());
    }

    // Calculate minting duration (max 34 minutes)
    let minutes = std::cmp::min(duration_since_last_mint / 60, 34);

    // Calculate tokens to mint
    let tokens_to_mint = ((2_833_333_333 * minutes as u64) / 10) as u64;

    // Update player's last minted timestamp
    // Update the player account accordingly

    // Mint tokens to player's reward address
    mint_tokens(game, &player.reward_address, tokens_to_mint);

    Ok(())
}

fn mint_tokens(game: &mut Account<Game>, address: &Pubkey, amount: u64) {
    if let Some(balance_entry) = game.token_balances.iter_mut().find(|tb| tb.address == *address) {
        balance_entry.balance += amount;
    } else {
        game.token_balances.push(TokenBalance {
            address: *address,
            balance: amount,
        });
    }
    game.total_token_supply += amount;
}

// Define custom errors

#[error_code]
pub enum ErrorCode {
    #[msg("Unauthorized.")]
    Unauthorized,
    #[msg("Not in punch-in period.")]
    NotInPunchInPeriod,
    #[msg("Not in mint period.")]
    NotInMintPeriod,
    #[msg("Insufficient stake. Minimum 32,000 tokens required to punch in.")]
    InsufficientStake,
    #[msg("Player name already exists.")]
    PlayerNameExists,
    #[msg("Validator not registered.")]
    ValidatorNotRegistered,
    #[msg("Hash conversion error.")]
    HashConversionError,
    #[msg("Invalid timestamp.")]
    InvalidTimestamp,
    #[msg("Game number mismatch.")]
    GameNumberMismatch,
    #[msg("Game status has already been set and cannot be changed.")]
    GameStatusAlreadySet,
    #[msg("Game is blacklisted.")]
    GameIsBlacklisted,
    #[msg("Game is not whitelisted.")]
    GameNotWhitelisted,
    // Add other error codes as needed...
}
