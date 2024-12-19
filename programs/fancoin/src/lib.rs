use anchor_lang::prelude::*;
use sha3::{Digest, Keccak256};
use std::convert::TryInto;

// If you don't actually use Utc, TimeZone, Timelike, remove them entirely:
// use chrono::{Utc, TimeZone, Timelike};

declare_id!("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut");

const DECIMALS: u64 = 1_000_000_000; // 6 decimal places

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct PlayerInfo {
    pub key: Pubkey,
    pub name: String,
}

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
        game.status = 0;
        game.description = description;
        game.validators = Vec::new();
        game.shards = Vec::new();
        game.token_balances = Vec::new();
        game.total_token_supply = 0;
        game.last_seed = None;
        game.last_punch_in_time = None;
        game.minting_agreements = Vec::new();
        game.prefix_sums = Vec::new();
        game.player_map = Vec::new(); // Now it's a Vec<PlayerInfo>
        Ok(())
    }

    pub fn update_game_status(ctx: Context<UpdateGameStatus>, game_number: u32, new_status: u8, description: String) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let dapp = &ctx.accounts.dapp;
        let signer = &ctx.accounts.signer;

        if dapp.owner != signer.key() {
            return Err(ErrorCode::Unauthorized.into());
        }

        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        // Check if current status is 'Probationary'
        if game.status != 0 {
            return Err(ErrorCode::GameStatusAlreadySet.into());
        }

        game.status = new_status;
        game.description = description;

        Ok(())
    }

    pub fn get_player_list(ctx: Context<GetPlayerList>, game_number: u32, start_index: u32, end_index: u32) -> Result<()> {
        let game = &ctx.accounts.game;
        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        let total_players = if let Some(&last) = game.prefix_sums.last() {
            last
        } else {
            0
        };

        if start_index >= total_players {
            return Err(ErrorCode::InvalidRange.into());
        }

        let clamped_end = if end_index > total_players {
            total_players
        } else {
            end_index
        };

        if start_index > clamped_end {
            return Err(ErrorCode::InvalidRange.into());
        }

        let s = match game.prefix_sums.binary_search(&start_index) {
            Ok(idx) => idx,
            Err(idx) => {
                if idx == 0 { 0 } else { idx - 1 }
            }
        };

        let offset_in_shard = start_index - game.prefix_sums[s];

        let mut current_index = start_index;
        let mut shard_index = s;

        while current_index < clamped_end && shard_index < game.shards.len() {
            let shard = &game.shards[shard_index];
            let shard_len = shard.players.len() as u32;

            let start_offset = if current_index == start_index { offset_in_shard } else { 0 };

            if start_offset >= shard_len {
                shard_index += 1;
                continue;
            }

            let available_in_shard = shard_len.saturating_sub(start_offset);
            let needed = clamped_end - current_index;
            let to_print = std::cmp::min(available_in_shard, needed);
            let end_offset = start_offset + to_print;

            for i in start_offset..end_offset {
                let global_index = current_index;
                let pkey = shard.players[i as usize];

                if let Some(player_info) = game.player_map.iter().find(|pi| pi.key == pkey) {
                    msg!("Player {}: {} (Name: {})", global_index, pkey, player_info.name);
                } else {
                    msg!("Player {}: {} (No name found)", global_index, pkey);
                }

                current_index += 1;
            }

            shard_index += 1;
        }

        Ok(())
    }

    pub fn get_validator_list(ctx: Context<GetValidatorList>, game_number: u32, start_index: u32, end_index: u32) -> Result<()> {
        let game = &ctx.accounts.game;
        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        let total_validators = game.validators.len() as u32;
        if start_index >= total_validators || end_index > total_validators || start_index > end_index {
            return Err(ErrorCode::InvalidRange.into());
        }

        for i in start_index..end_index {
            let v = &game.validators[i as usize];
            msg!("Validator {}: {}", i, v.address);
        }

        Ok(())
    }

    pub fn change_player_name(ctx: Context<ChangePlayerName>, new_name: String) -> Result<()> {
        let player = &mut ctx.accounts.player;
        let now = Clock::get()?.unix_timestamp;
        let one_week = 7 * 24 * 3600;

        if let Some(last_change) = player.last_name_change {
            if now - last_change < one_week {
                return Err(ErrorCode::NameChangeCooldown.into());
            }
        }

        player.name = new_name;
        player.last_name_change = Some(now);
        Ok(())
    }

    pub fn punch_in(ctx: Context<PunchIn>, game_number: u32) -> Result<()> {
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        let validator_key = ctx.accounts.validator.key();
        let validator_info = ctx.accounts.validator.to_account_info();
        let game_info = ctx.accounts.game.to_account_info();

        let game = &mut ctx.accounts.game;

        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        if game.status == 2 {
            return Err(ErrorCode::GameIsBlacklisted.into());
        }

        let already_exists = game.validators.iter().any(|v| v.address == validator_key);
        if !already_exists {
            add_space_and_fund(&game_info, &validator_info, 200)?;
        }

        let validator = &mut ctx.accounts.validator;

        if let Some(existing_validator) = game.validators.iter_mut().find(|v| v.address == validator.key()) {
            existing_validator.last_activity = current_time;
        } else {
            game.validators.push(Validator {
                address: validator.key(),
                last_activity: current_time,
            });
        }

        let seed_data = validator.key().to_bytes();
        let slot_bytes = clock.slot.to_le_bytes();
        let mut hasher = Keccak256::new();
        hasher.update(&seed_data);
        hasher.update(&slot_bytes);
        let hash_result = hasher.finalize();

        let seed = u64::from_le_bytes(
            hash_result[0..8]
                .try_into()
                .map_err(|_| ErrorCode::HashConversionError)?
        );

        game.last_seed = Some(seed);
        game.last_punch_in_time = Some(current_time);

        Ok(())
    }

    pub fn register_player(ctx: Context<RegisterPlayer>, game_number: u32, name: String, reward_address: Pubkey) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let player_account = &mut ctx.accounts.player;
        let user = &ctx.accounts.user;

        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        if game.status == 2 {
            return Err(ErrorCode::GameIsBlacklisted.into());
        }

        if game.shards.iter().any(|shard| {
            shard.players.iter().any(|&p_key| p_key == player_account.key())
        }) {
            return Err(ErrorCode::PlayerNameExists.into());
        }

        let game_info = game.to_account_info();
        let user_info = user.to_account_info();
        add_space_and_fund(&game_info, &user_info, 2000)?;

        player_account.name = name.clone();
        player_account.address = user.key();
        player_account.reward_address = reward_address;
        player_account.last_minted = None;
        player_account.last_name_change = None;
        player_account.last_reward_address_change = None;

        let shard_capacity = 3;
        let mut added = false;
        for shard in &mut game.shards {
            if shard.players.len() < shard_capacity {
                shard.players.push(player_account.key());
                added = true;
                break;
            }
        }
        if !added {
            let new_shard = Shard {
                players: vec![player_account.key()],
            };
            game.shards.push(new_shard);
        }

        game.player_map.push(PlayerInfo {
            key: player_account.key(),
            name: name.clone(),
        });

        update_prefix_sums(game);
        Ok(())
    }

    pub fn register_player_debug(ctx: Context<RegisterPlayer>, game_number: u32, name: String, reward_address: Pubkey) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let player_account = &mut ctx.accounts.player;

        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        if game.status == 2 {
            return Err(ErrorCode::GameIsBlacklisted.into());
        }

        if game.shards.iter().any(|shard| {
            shard.players.iter().any(|&p_key| p_key == player_account.key())
        }) {
            return Err(ErrorCode::PlayerNameExists.into());
        }

        player_account.name = name.clone();
        player_account.address = ctx.accounts.user.key();
        player_account.reward_address = reward_address;
        player_account.last_minted = None;
        player_account.last_name_change = None;
        player_account.last_reward_address_change = None;

        let shard_capacity = 3;
        let game_info = game.to_account_info();
        let user_info = ctx.accounts.user.to_account_info();

        if let Some(last_shard) = game.shards.last_mut() {
            if last_shard.players.len() < shard_capacity {
                last_shard.players.push(player_account.key());
            } else {
                add_space_and_fund(&game_info, &user_info, 2170)?;
                let new_shard = Shard {
                    players: vec![player_account.key()],
                };
                game.shards.push(new_shard);
            }
        } else {
            add_space_and_fund(&game_info, &user_info, 2170)?;
            let new_shard = Shard {
                players: vec![player_account.key()],
            };
            game.shards.push(new_shard);
        }

        game.player_map.push(PlayerInfo {
            key: player_account.key(),
            name: name.clone(),
        });

        update_prefix_sums(game);
        Ok(())
    }

    pub fn submit_minting_list(ctx: Context<SubmitMintingList>, game_number: u32, player_names: Vec<String>) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let validator = &ctx.accounts.validator;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        if !game.validators.iter().any(|v| v.address == validator.key()) {
            return Err(ErrorCode::ValidatorNotRegistered.into());
        }

        for player_name in player_names {
            if let Some(agreement) = game.minting_agreements.iter_mut().find(|ma| ma.player_name == player_name) {
                if !agreement.validators.contains(&validator.key()) {
                    agreement.validators.push(validator.key());
                }
            } else {
                game.minting_agreements.push(MintingAgreement {
                    player_name: player_name.clone(),
                    validators: vec![validator.key()],
                });
            }
        }

        let failover_tolerance = calculate_failover_tolerance(game.validators.len());

        let mut successful_mints = Vec::new();
        let mut validator_rewards = Vec::new();

        let mut remaining_agreements = Vec::new();

        for agreement in &game.minting_agreements {
            if agreement.validators.len() >= 2 {
                let seed = match game.last_seed {
                    Some(s) => s,
                    None => {
                        remaining_agreements.push(agreement.clone());
                        continue;
                    }
                };

                let first_validator = agreement.validators[0];
                let first_group_id = calculate_group_id(&first_validator, seed)?;

                let mut validators_in_same_group = true;
                for validator_key in agreement.validators.iter().skip(1) {
                    let group_id = calculate_group_id(validator_key, seed)?;
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
                    successful_mints.push(agreement.player_name.clone());

                    for validator_key in &agreement.validators {
                        if let Some(entry) = validator_rewards.iter_mut().find(|(vk, _)| vk == validator_key) {
                            entry.1 += 1_618_000_000;
                        } else {
                            validator_rewards.push((*validator_key, 1_618_000_000));
                        }
                    }
                } else {
                    remaining_agreements.push(agreement.clone());
                }
            } else {
                remaining_agreements.push(agreement.clone());
            }
        }

        for player_name in successful_mints {
            mint_tokens_for_player(game, &player_name, current_time)?;
        }

        for (validator_key, reward) in validator_rewards {
            mint_tokens(game, &validator_key, reward);
        }

        game.minting_agreements = remaining_agreements;

        Ok(())
    }

}

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(init, payer = user, space = DApp::LEN, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

// If Game::LEN not needed, use a fixed large value, e.g., space = 50000
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct InitializeGame<'info> {
    #[account(init, payer = user, space = 50000, seeds = [b"game", &game_number.to_le_bytes()], bump)]
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
#[instruction()]
pub struct ChangePlayerName<'info> {
    #[account(mut)]
    pub player: Account<'info, Player>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct PunchIn<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    #[account(mut)]
    pub validator: Signer<'info>,
    pub system_program: Program<'info, System>,
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

#[account]
pub struct DApp {
    pub owner: Pubkey,
}

impl DApp {
    pub const LEN: usize = 8 + 32;
}

#[account]
pub struct Game {
    pub game_number: u32,
    pub status: u8,
    pub description: String,
    pub validators: Vec<Validator>,
    pub shards: Vec<Shard>,
    pub token_balances: Vec<TokenBalance>,
    pub total_token_supply: u64,
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,
    pub minting_agreements: Vec<MintingAgreement>,
    pub prefix_sums: Vec<u32>,
    pub player_map: Vec<PlayerInfo>, // Mapping from player address to name
}

#[derive(Default, Clone, Copy, PartialEq, Eq)]
pub enum GameStatus {
    #[default]
    Probationary = 0,
    Whitelisted = 1,
    Blacklisted = 2,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Validator {
    pub address: Pubkey,
    pub last_activity: i64,
}

#[account]
pub struct Player {
    pub name: String,
    pub address: Pubkey,
    pub reward_address: Pubkey,
    pub last_minted: Option<i64>,
    pub last_name_change: Option<i64>,
    pub last_reward_address_change: Option<i64>,
}

impl Player {
    pub const MAX_NAME_LEN: usize = 16;
    pub const LEN: usize =
        4 + Self::MAX_NAME_LEN +
        32 +
        32 +
        9 +
        9 +
        9;
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Shard {
    pub players: Vec<Pubkey>,
}

impl Shard {
    pub const MAX_PLAYERS: usize = 3;
    pub const LEN: usize = 4 + (Self::MAX_PLAYERS * 32);
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct TokenBalance {
    pub address: Pubkey,
    pub balance: u64,
}

impl TokenBalance {
    pub const LEN: usize = 32 + 8;
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct GetPlayerList<'info> {
    #[account(seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct GetValidatorList<'info> {
    #[account(seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct MintingAgreement {
    pub player_name: String,
    pub validators: Vec<Pubkey>,
}

impl MintingAgreement {
    pub const MAX_PLAYER_NAME_LEN: usize = 16;
    pub const MAX_VALIDATORS: usize = 5;
    pub const LEN: usize = 4 + Self::MAX_PLAYER_NAME_LEN + (4 + Self::MAX_VALIDATORS * 32);
}

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
    #[msg("Name cooldown still going.")]
    NameChangeCooldown,
    #[msg("Invalid seeds.")]
    InvalidSeeds,
    #[msg("Invalid range.")]
    InvalidRange,
    #[msg("No seed generated.")]
    NoSeed,
}

pub fn get_validator_info(ctx: Context<GetValidatorList>, validator: Pubkey) -> Result<()> {
    let game = &ctx.accounts.game;
    let seed = game
        .last_seed
        .ok_or(ErrorCode::NoSeed)?;
    let group_id = calculate_group_id(&validator, seed)?;

    emit!(ValidatorInfoEvent { seed, group_id });
    Ok(())
}

fn is_punch_in_period(_current_time: i64) -> Result<bool> {
    // If not used, just return Ok(true) or remove entirely.
    // For example:
    Ok(true)
}

fn is_mint_period(_current_time: i64) -> Result<bool> {
    Ok(true)
}

fn update_prefix_sums(game: &mut Game) {
    game.prefix_sums.clear();
    game.prefix_sums.push(0);
    let mut running_total = 0u32;
    for shard in &game.shards {
        running_total = running_total.saturating_add(shard.players.len() as u32);
        game.prefix_sums.push(running_total);
    }
}

fn get_stake(token_balances: &Vec<TokenBalance>, address: &Pubkey) -> u64 {
    token_balances.iter()
        .find(|tb| &tb.address == address)
        .map(|tb| tb.balance)
        .unwrap_or(0)
}

fn calculate_failover_tolerance(total_validators: usize) -> usize {
    let total_groups = (total_validators + 3) / 4;
    let num_digits = total_groups.to_string().len();
    num_digits + 1
}

fn calculate_group_id(address: &Pubkey, seed: u64) -> Result<u64> {
    let mut hasher = Keccak256::new();
    hasher.update(address.to_bytes());
    hasher.update(&seed.to_le_bytes());
    let result = hasher.finalize();
    let bytes: [u8; 8] = result[0..8]
        .try_into()
        .map_err(|_| ErrorCode::HashConversionError)?;
    Ok(u64::from_be_bytes(bytes))
}

fn add_space_and_fund<'info>(
    game_info: &AccountInfo<'info>,
    user_info: &AccountInfo<'info>,
    additional_space: usize,
) -> Result<()> {
    let rent = Rent::get()?;
    let old_len = game_info.data_len();
    let new_len = old_len + additional_space;

    let required_rent = rent.minimum_balance(new_len);
    let current_lamports = game_info.lamports();
    let required_lamports = required_rent.saturating_sub(current_lamports);

    if required_lamports > 0 {
        let transfer_ix = anchor_lang::solana_program::system_instruction::transfer(
            user_info.key,
            game_info.key,
            required_lamports,
        );
        anchor_lang::solana_program::program::invoke(
            &transfer_ix,
            &[
                user_info.clone(),
                game_info.clone(),
            ],
        )?;
    }

    game_info.realloc(new_len, false)?;

    Ok(())
}

fn mint_tokens_for_player(game: &mut Account<Game>, player_name: &str, _current_time: i64) -> Result<()> {
    // Placeholder: If not used, remove logic or implement as needed.
    let player_pubkey = Pubkey::default();

    let _player = Player {
        name: player_name.to_string(),
        address: player_pubkey,
        reward_address: player_pubkey,
        last_name_change: None,
        last_reward_address_change: None,
        last_minted: None,
    };

    // Just skip minting logic if not needed.
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

#[event]
pub struct ValidatorInfoEvent {
    pub seed: u64,
    pub group_id: u64,
}
