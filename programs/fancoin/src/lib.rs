use anchor_lang::prelude::*;
use sha3::{Digest, Keccak256};
use std::convert::TryInto;

// Program ID
declare_id!("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut");

#[program]
pub mod fancoin {
    use super::*;

    // ----------------------------------------------------------------
    // 1) DApp-level instructions (UNCHANGED)
    // ----------------------------------------------------------------
    pub fn initialize_dapp(ctx: Context<InitializeDapp>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        dapp.owner = ctx.accounts.user.key();
        dapp.global_player_count = 0;
        Ok(())
    }

    pub fn relinquish_ownership(ctx: Context<RelinquishOwnership>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        require!(dapp.owner == ctx.accounts.signer.key(), ErrorCode::Unauthorized);
        dapp.owner = Pubkey::default();
        Ok(())
    }

    // ----------------------------------------------------------------
    // 2) Minimal Game instructions (UNCHANGED)
    // ----------------------------------------------------------------
    pub fn initialize_game(
        ctx: Context<InitializeGame>,
        game_number: u32,
        description: String,
    ) -> Result<()> {
        let dapp = &ctx.accounts.dapp;
        require!(
            dapp.owner == ctx.accounts.user.key() || dapp.owner == Pubkey::default(),
            ErrorCode::Unauthorized
        );
        let game = &mut ctx.accounts.game;
        game.game_number = game_number;
        game.description = description;
        game.status = 0;
        game.validator_count = 0;
        game.last_seed = None;
        game.last_punch_in_time = None;
        Ok(())
    }

    pub fn update_game_status(
        ctx: Context<UpdateGameStatus>,
        game_number: u32,
        new_status: u8,
        description: String,
    ) -> Result<()> {
        let dapp = &ctx.accounts.dapp;
        let game = &mut ctx.accounts.game;
        require!(dapp.owner == ctx.accounts.signer.key(), ErrorCode::Unauthorized);
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        game.status = new_status;
        game.description = description;
        Ok(())
    }

    pub fn punch_in(ctx: Context<PunchIn>, game_number: u32) -> Result<()> {
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let game = &mut ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        require!(game.status != 2, ErrorCode::GameIsBlacklisted);
        let validator_key = ctx.accounts.validator.key();
        let mut hasher = Keccak256::new();
        hasher.update(validator_key.to_bytes());
        hasher.update(clock.slot.to_le_bytes());
        let hash_res = hasher.finalize();
        let seed = u64::from_le_bytes(
            hash_res[0..8].try_into().map_err(|_| ErrorCode::HashConversionError)?
        );
        game.last_seed = Some(seed);
        game.last_punch_in_time = Some(current_time);
        Ok(())
    }

    // ----------------------------------------------------------------
    // 3) Player + Validator PDAs (UNCHANGED)
    // ----------------------------------------------------------------
    pub fn register_player_pda(
        ctx: Context<RegisterPlayerPda>,
        name: String,
        authority_address: Pubkey,
        reward_address: Pubkey,
    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        let player = &mut ctx.accounts.player_pda;
        player.name = name;
        player.authority = authority_address;
        player.reward_address = reward_address;
        player.last_name_change = None;
        player.last_reward_change = None;
        // NEW: partial_validators is empty on creation
        player.partial_validators = Vec::new();

        dapp.global_player_count += 1;
        Ok(())
    }

    pub fn register_validator_pda(ctx: Context<RegisterValidatorPda>, game_number: u32) -> Result<()> {
        let game = &mut ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        let val_pda = &mut ctx.accounts.validator_pda;
        val_pda.address = ctx.accounts.user.key();
        val_pda.last_activity = Clock::get()?.unix_timestamp;
        game.validator_count += 1;
        Ok(())
    }

    pub fn get_player_list_pda_page(
        ctx: Context<GetPlayerListPdaPage>,
        start_index: u32,
        end_index: u32,
    ) -> Result<()> {
        let dapp = &ctx.accounts.dapp;
        require!(start_index < dapp.global_player_count, ErrorCode::InvalidRange);
        let clamped_end = end_index.min(dapp.global_player_count);
        require!(start_index <= clamped_end, ErrorCode::InvalidRange);
        let needed = (clamped_end - start_index) as usize;
        require!(ctx.remaining_accounts.len() >= needed, ErrorCode::InvalidRange);
        for (offset, acc_info) in ctx.remaining_accounts.iter().enumerate() {
            let i = start_index + offset as u32;
            if i >= clamped_end {
                break;
            }
            let maybe_player_pda = Account::<PlayerPda>::try_from(acc_info);
            if let Ok(player_pda) = maybe_player_pda {
                msg!("PlayerPda #{} => name: {}", i, player_pda.name);
            } else {
                msg!("PlayerPda #{} => <cannot load PDA>", i);
            }
        }
        Ok(())
    }

    pub fn get_validator_list_pda_page(
        ctx: Context<GetValidatorListPdaPage>,
        game_number: u32,
        start_index: u32,
        end_index: u32,
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        require!(start_index < game.validator_count, ErrorCode::InvalidRange);
        let clamped_end = end_index.min(game.validator_count);
        require!(start_index <= clamped_end, ErrorCode::InvalidRange);
        let needed = (clamped_end - start_index) as usize;
        require!(ctx.remaining_accounts.len() >= needed, ErrorCode::InvalidRange);
        for (offset, acc_info) in ctx.remaining_accounts.iter().enumerate() {
            let i = start_index + offset as u32;
            if i >= clamped_end {
                break;
            }
            let maybe_val_pda = Account::<ValidatorPda>::try_from(acc_info);
            if let Ok(val_pda) = maybe_val_pda {
                msg!("ValidatorPda #{} => address: {}", i, val_pda.address);
            } else {
                msg!("ValidatorPda #{} => <cannot load PDA>", i);
            }
        }
        Ok(())
    }

    // ----------------------------------------------------------------
    // 4) Name/Reward cooldown (UNCHANGED)
    // ----------------------------------------------------------------
    pub fn update_player_name_cooldown(ctx: Context<UpdatePlayerNameCooldown>, new_name: String) -> Result<()> {
        let pda = &mut ctx.accounts.player_pda;
        let now = Clock::get()?.unix_timestamp;
        let one_week = 7 * 24 * 3600;
        require!(pda.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);
        if let Some(last_change) = pda.last_name_change {
            require!(now - last_change >= one_week, ErrorCode::NameChangeCooldown);
        }
        pda.name = new_name;
        pda.last_name_change = Some(now);
        Ok(())
    }

    pub fn update_player_reward_cooldown(ctx: Context<UpdatePlayerRewardCooldown>, new_reward: Pubkey) -> Result<()> {
        let pda = &mut ctx.accounts.player_pda;
        let now = Clock::get()?.unix_timestamp;
        let one_week = 7 * 24 * 3600;
        require!(pda.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);
        if let Some(last_change) = pda.last_reward_change {
            require!(now - last_change >= one_week, ErrorCode::NameChangeCooldown);
        }
        pda.reward_address = new_reward;
        pda.last_reward_change = Some(now);
        Ok(())
    }

    // ----------------------------------------------------------------
    // 5) Old approach: submit_minting_list with game.minting_agreements (UNCHANGED)
    // ----------------------------------------------------------------
    pub fn submit_minting_list(
        ctx: Context<SubmitMintingList>,
        game_number: u32,
        player_names: Vec<String>,
    ) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let validator_signer = &ctx.accounts.validator;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        // Basic checks
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Make sure signer is recognized
        let mut found_val_pda = false;
        for acc_info in ctx.remaining_accounts.iter() {
            if let Ok(val_pda) = Account::<ValidatorPda>::try_from(acc_info) {
                if val_pda.address == validator_signer.key() {
                    found_val_pda = true;
                    break;
                }
            }
        }
        require!(found_val_pda, ErrorCode::ValidatorNotRegistered);

        // Insert or update each MintingAgreement in the old `game.minting_agreements`.
        for player_name in player_names {
            if let Some(agreement) =
                game.minting_agreements.iter_mut().find(|ma| ma.player_name == player_name)
            {
                if !agreement.validators.contains(&validator_signer.key()) {
                    agreement.validators.push(validator_signer.key());
                }
            } else {
                game.minting_agreements.push(MintingAgreement {
                    player_name,
                    validators: vec![validator_signer.key()],
                });
            }
        }

        // For example: failover_tolerance
        let failover_tolerance = calculate_failover_tolerance(game.validator_count as usize);

        let mut successful_mints = Vec::new();
        let mut validator_rewards = Vec::new(); // (validator_pubkey, reward_amt)
        let mut remaining_agreements = Vec::new();

        for agreement in &game.minting_agreements {
            if agreement.validators.len() >= 2 {
                // Must have a seed, else skip
                let seed = match game.last_seed {
                    Some(s) => s,
                    None => {
                        remaining_agreements.push(agreement.clone());
                        continue;
                    }
                };

                // grouping logic
                let first_validator = agreement.validators[0];
                let first_group_id = calculate_group_id(&first_validator, seed)?;

                let mut all_same_group = true;
                for validator_key in agreement.validators.iter().skip(1) {
                    let group_id = calculate_group_id(validator_key, seed)?;
                    let distance = if group_id > first_group_id {
                        group_id - first_group_id
                    } else {
                        first_group_id - group_id
                    };
                    if distance > failover_tolerance as u64 {
                        all_same_group = false;
                        break;
                    }
                }

                if all_same_group {
                    successful_mints.push(agreement.player_name.clone());
                    for validator_key in &agreement.validators {
                        if let Some(entry) =
                            validator_rewards.iter_mut().find(|(vk, _)| vk == validator_key)
                        {
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

        // Actually "mint" for each player
        for player_name in successful_mints {
            mint_tokens_for_player(game, &player_name, current_time)?;
        }

        // Reward each validator
        for (validator_key, reward_amt) in validator_rewards {
            mint_tokens(game, &validator_key, reward_amt);
        }

        // keep leftover
        game.minting_agreements = remaining_agreements;
        Ok(())
    }

    // ----------------------------------------------------------------
    // 6) NEW APPROACH: Partial Approvals in Each PlayerPda
    // ----------------------------------------------------------------

    /// Each validator calls this to add themselves to the player's `partial_validators`.
    /// Over time, once multiple validators have approved, we can finalize minting.
    pub fn approve_player_minting(
        ctx: Context<ApprovePlayerMinting>,
        game_number: u32,
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        let validator_signer = &ctx.accounts.validator;
        let player_pda = &mut ctx.accounts.player_pda;

        // Basic checks
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Make sure signer is recognized
        let mut found_val_pda = false;
        for acc_info in ctx.remaining_accounts.iter() {
            if let Ok(val_pda) = Account::<ValidatorPda>::try_from(acc_info) {
                if val_pda.address == validator_signer.key() {
                    found_val_pda = true;
                    break;
                }
            }
        }
        require!(found_val_pda, ErrorCode::ValidatorNotRegistered);

        // Add validator to partial_validators if not already present
        if !player_pda.partial_validators.contains(&validator_signer.key()) {
            player_pda.partial_validators.push(validator_signer.key());
        }

        msg!(
            "Approved player={} by validator={}. Now has {} partial approvals.",
            player_pda.name,
            validator_signer.key(),
            player_pda.partial_validators.len()
        );

        Ok(())
    }

    /// Once the player has enough partial validators, we do the same group ID + failover logic,
    /// mint tokens for the player, reward the validators, and clear partial_validators.
    pub fn finalize_player_minting(
        ctx: Context<FinalizePlayerMinting>,
        game_number: u32,
    ) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let player_pda = &mut ctx.accounts.player_pda;

        // Must match game
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Need at least 2 validators for this logic
        if player_pda.partial_validators.len() < 2 {
            msg!(
                "Player {} has only {} partial validators; skipping finalize.",
                player_pda.name,
                player_pda.partial_validators.len()
            );
            return Ok(());
        }

        // Must have a seed
        let seed = match game.last_seed {
            Some(s) => s,
            None => {
                msg!("No last_seed in game. Cannot finalize.");
                return Ok(());
            }
        };

        let failover_tolerance = calculate_failover_tolerance(game.validator_count as usize);

        // grouping logic
        let first_validator = player_pda.partial_validators[0];
        let first_group_id = calculate_group_id(&first_validator, seed)?;

        let mut all_same_group = true;
        for validator_key in player_pda.partial_validators.iter().skip(1) {
            let group_id = calculate_group_id(validator_key, seed)?;
            let distance = if group_id > first_group_id {
                group_id - first_group_id
            } else {
                first_group_id - group_id
            };
            if distance > failover_tolerance as u64 {
                all_same_group = false;
                break;
            }
        }

        if all_same_group {
            // Mint to the player
            mint_tokens_for_player(game, &player_pda.name, current_time)?;

            // Reward each validator
            for vk in &player_pda.partial_validators {
                mint_tokens(game, vk, 1_618_000_000);
            }

            // Clear partial_validators
            player_pda.partial_validators.clear();

            msg!(
                "Success: minted tokens for player={} and rewarded {} validators.",
                player_pda.name,
                game.validator_count
            );
        } else {
            msg!(
                "Failover check failed for player {}. partial_validators remain.",
                player_pda.name
            );
        }

        Ok(())
    }
}

// --------------------------------------------------------------------
// Data + Accounts (UNCHANGED, except PlayerPda gets partial_validators)
// --------------------------------------------------------------------

#[account]
pub struct DApp {
    pub owner: Pubkey,
    pub global_player_count: u32,
}
impl DApp {
    pub const LEN: usize = 8 + 32 + 4;
}

#[account]
pub struct Game {
    pub game_number: u32,
    pub validator_count: u32,
    pub status: u8,
    pub description: String,
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,

    // Keep the old "minting_agreements" vector so the old instruction remains valid
    pub minting_agreements: Vec<MintingAgreement>,
}
impl Game {
    pub const LEN: usize = 
        8 +
        (4 + 4 + 1) +         // game_number, validator_count, status
        (4 + 64) +            // description up to ~64 chars (example)
        9 +                   // Option<u64>
        9 +                   // Option<i64>
        4 + (5 * (4 + 32));   
        // The above line is an approximate space for a small vector of MintingAgreement.
        // In real usage, you'd want a bigger buffer or a more advanced approach.
}

// This struct is used in the old approach (unchanged).
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct MintingAgreement {
    pub player_name: String,
    pub validators: Vec<Pubkey>,
}

#[account]
pub struct PlayerPda {
    pub name: String,
    pub authority: Pubkey,
    pub reward_address: Pubkey,
    pub last_name_change: Option<i64>,
    pub last_reward_change: Option<i64>,

    // NEW FIELD: partial validator approvals
    pub partial_validators: Vec<Pubkey>,
}

// For simplicity, we define a maximum capacity for partial_validators.
impl PlayerPda {
    // If we want up to 10 partial validators, do the math:
    // Vector overhead = 4 bytes for length + (10 * 32 bytes) = 324 bytes
    // Add to existing fields
    pub const MAX_PARTIAL_VALS: usize = 10;
    pub const LEN: usize =
        8 +                // Anchor discriminator
        (4 + 32) +         // name => up to 32 chars (ex. 4 + 32)
        32 +               // authority
        32 +               // reward_address
        9 +                // Option<i64> (last_name_change)
        9 +                // Option<i64> (last_reward_change)
        4 + (Self::MAX_PARTIAL_VALS * 32); // partial_validators
}

#[account]
pub struct ValidatorPda {
    pub address: Pubkey,
    pub last_activity: i64,
}
impl ValidatorPda {
    pub const LEN: usize = 8 + 32 + 8;
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
        4 + Self::MAX_NAME_LEN
        + 32
        + 32
        + 9
        + 9
        + 9;
}

// --------------------------------------------------------------------
// Accounts (UNCHANGED, except the new Approve/Finalize contexts)
// --------------------------------------------------------------------

#[derive(Accounts)]
pub struct InitializeDapp<'info> {
    #[account(init, payer = user, space = DApp::LEN, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct RelinquishOwnership<'info> {
    #[account(mut, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
    #[account(mut)]
    pub signer: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(game_number: u32, description: String)]
pub struct InitializeGame<'info> {
    #[account(
        init,
        payer = user,
        // We'll allocate a bit more space for 'minting_agreements'
        space = 8 + 4 + 4 + 1 + 72 + 9 + 9 + 4 + (5 * (4 + 32)),
        seeds = [b"game", &game_number.to_le_bytes()],
        bump
    )]
    pub game: Account<'info, Game>,
    #[account(seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
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
    #[account(mut)]
    pub validator: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct RegisterValidatorPda<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    #[account(
        init,
        payer = user,
        space = ValidatorPda::LEN,
        seeds = [b"validator", &game_number.to_le_bytes()[..], &game.validator_count.to_le_bytes()[..]],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct RegisterPlayerPda<'info> {
    #[account(mut, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
    #[account(
        init,
        payer = user,
        // Updated space for new partial_validators field
        space = PlayerPda::LEN,
        seeds = [
            b"player_pda",
            &dapp.global_player_count.to_le_bytes()[..]
        ],
        bump
    )]
    pub player_pda: Account<'info, PlayerPda>,
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
pub struct UpdatePlayerNameCooldown<'info> {
    #[account(mut)]
    pub player_pda: Account<'info, PlayerPda>,
    #[account(mut)]
    pub user: Signer<'info>,
}

#[derive(Accounts)]
pub struct UpdatePlayerRewardCooldown<'info> {
    #[account(mut)]
    pub player_pda: Account<'info, PlayerPda>,
    #[account(mut)]
    pub user: Signer<'info>,
}

#[derive(Accounts)]
pub struct GetPlayerListPdaPage<'info> {
    #[account(seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct GetValidatorListPdaPage<'info> {
    #[account(seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
}

// NEW: For partial approvals
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct ApprovePlayerMinting<'info> {
    #[account(seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    #[account(mut)]
    pub validator: Signer<'info>,

    #[account(mut)]
    pub player_pda: Account<'info, PlayerPda>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct FinalizePlayerMinting<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    #[account(mut)]
    pub player_pda: Account<'info, PlayerPda>,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Unauthorized.")]
    Unauthorized,
    #[msg("Not in punch-in period.")]
    NotInPunchInPeriod,
    #[msg("Not in mint period.")]
    NotInMintPeriod,
    #[msg("Insufficient stake.")]
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
    #[msg("Game status already set.")]
    GameStatusAlreadySet,
    #[msg("Game is blacklisted.")]
    GameIsBlacklisted,
    #[msg("Game not whitelisted.")]
    GameNotWhitelisted,
    #[msg("Name cooldown active.")]
    NameChangeCooldown,
    #[msg("Invalid seeds.")]
    InvalidSeeds,
    #[msg("Invalid range.")]
    InvalidRange,
    #[msg("No seed generated.")]
    NoSeed,
    #[msg("Account already expanded.")]
    AlreadyExpanded,
}

// --------------------------------------------------------------------
// Utility functions (UNCHANGED)
// --------------------------------------------------------------------
fn calculate_failover_tolerance(total_validators: usize) -> usize {
    let total_groups = (total_validators + 3) / 4;
    let num_digits = total_groups.to_string().len();
    num_digits + 1
}

fn calculate_group_id(address: &Pubkey, seed: u64) -> Result<u64> {
    let mut hasher = Keccak256::new();
    hasher.update(address.to_bytes());
    hasher.update(seed.to_le_bytes());
    let result = hasher.finalize();
    let bytes: [u8; 8] = result[0..8]
        .try_into()
        .map_err(|_| ErrorCode::HashConversionError)?;
    Ok(u64::from_be_bytes(bytes))
}

fn mint_tokens_for_player(_game: &mut Account<Game>, _player_name: &str, _current_time: i64) -> Result<()> {
    // This remains your placeholder for actual "minting" logic
    // (like awarding in-game currency or tokens).
    Ok(())
}

fn mint_tokens(_game: &mut Account<Game>, _address: &Pubkey, _amount: u64) {
    // Also a placeholder for actual SPL mint or scoreboard logic.
}

#[event]
pub struct ValidatorInfoEvent {
    pub seed: u64,
    pub group_id: u64,
}
