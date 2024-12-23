use anchor_lang::prelude::*;
use sha3::{Digest, Keccak256};
use std::convert::TryInto;

//
// ------------------------------------------------------------------
// Program ID
// ------------------------------------------------------------------
declare_id!("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut");

const DECIMALS: u64 = 1_000_000_000; // Optional, if you want

//
// ------------------------------------------------------------------
// [PROGRAM] fancoin
// ------------------------------------------------------------------
#[program]
pub mod fancoin {
    use super::*;

    // ------------------------------------------------------------------
    //  1) DApp-level instructions
    // ------------------------------------------------------------------

    /// Initialize a DApp that tracks the global count of players across *all* games.
    pub fn initialize_dapp(ctx: Context<InitializeDapp>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        dapp.owner = ctx.accounts.user.key();
        dapp.global_player_count = 0;
        Ok(())
    }

    /// (Optional) Relinquish ownership of the DApp.
    pub fn relinquish_ownership(ctx: Context<RelinquishOwnership>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        require!(dapp.owner == ctx.accounts.signer.key(), ErrorCode::Unauthorized);

        dapp.owner = Pubkey::default();
        Ok(())
    }

    // ------------------------------------------------------------------
    //  2) Minimal Game instructions
    // ------------------------------------------------------------------

    /// Initialize a minimal `Game` with basic fields (game_number, validator_count, etc.)
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
        game.status = 0; // e.g. 0 = NotStarted
        game.validator_count = 0;
        game.last_seed = None;
        game.last_punch_in_time = None;
        // If you want to store minimal 'minting_agreements' in game, set them as empty
        game.minting_agreements = Vec::new();
        Ok(())
    }

    pub fn update_game_status(
        ctx: Context<UpdateGameStatus>,
        game_number: u32,
        new_status: u8,
        description: String
    ) -> Result<()> {
        let dapp = &ctx.accounts.dapp;
        let game = &mut ctx.accounts.game;
        require!(dapp.owner == ctx.accounts.signer.key(), ErrorCode::Unauthorized);
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        game.status = new_status;
        game.description = description;
        Ok(())
    }

    /// Punch in as a validator (placeholder logic).
    pub fn punch_in(ctx: Context<PunchIn>, game_number: u32) -> Result<()> {
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        let game = &mut ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        require!(game.status != 2, ErrorCode::GameIsBlacklisted);

        // Example: compute some random seed from the validator's key + the current slot
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

    // ------------------------------------------------------------------
    //  3) Player + Validator PDAs
    // ------------------------------------------------------------------

    /// Create (register) a brand-new Player PDA. Increments the dapp.global_player_count.
    pub fn register_player_pda(
        ctx: Context<RegisterPlayerPda>,
        name: String,
        authority_address: Pubkey,
        reward_address: Pubkey,
    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        let player = &mut ctx.accounts.player_pda;
    
        // Fill in the fields of the newly created PlayerPda
        player.name = name;
        player.authority = authority_address;
        player.reward_address = reward_address;
        player.last_name_change = None;
        player.last_reward_change = None;
    
        // Increment the DApp’s global player counter.
        dapp.global_player_count += 1;
    
        Ok(())
    }

    /// Similarly, create a brand-new validator for a given Game
    pub fn register_validator_pda(
        ctx: Context<RegisterValidatorPda>,
        game_number: u32,
    ) -> Result<()> {
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

        // Ensure `start_index < end_index <= dapp.global_player_count`
        require!(start_index < dapp.global_player_count, ErrorCode::InvalidRange);
        let clamped_end = end_index.min(dapp.global_player_count);
        require!(start_index <= clamped_end, ErrorCode::InvalidRange);

        // We expect `end_index - start_index` PDAs in `ctx.remaining_accounts`
        let num_needed = (clamped_end - start_index) as usize;
        require!(ctx.remaining_accounts.len() >= num_needed, ErrorCode::InvalidRange);

        // Iterate
        for (offset, acc_info) in ctx.remaining_accounts.iter().enumerate() {
            let i = start_index + offset as u32;
            if i >= clamped_end {
                break;
            }
            let maybe_player_pda = Account::<PlayerPda>::try_from(acc_info);
            if let Ok(player_pda) = maybe_player_pda {
                msg!("PlayerPda #{} => name: {}", i, player_pda.name);
            } else {
                msg!("PlayerPda #{} => <unable to load PDA>", i);
            }
        }

        Ok(())
    }

    // ------------------------------------------------------------------
    //  7) New: get_validator_list_pda_page
    // ------------------------------------------------------------------
    /// A new instruction that logs `ValidatorPda` addresses for each index in `[start_index, end_index)`.
    /// The client must pass these PDAs in `remaining_accounts`.
    pub fn get_validator_list_pda_page(
        ctx: Context<GetValidatorListPdaPage>,
        game_number: u32,
        start_index: u32,
        end_index: u32,
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // Ensure start < end <= game.validator_count
        require!(start_index < game.validator_count, ErrorCode::InvalidRange);
        let clamped_end = end_index.min(game.validator_count);
        require!(start_index <= clamped_end, ErrorCode::InvalidRange);

        let num_needed = (clamped_end - start_index) as usize;
        require!(ctx.remaining_accounts.len() >= num_needed, ErrorCode::InvalidRange);

        // Iterate
        for (offset, acc_info) in ctx.remaining_accounts.iter().enumerate() {
            let i = start_index + offset as u32;
            if i >= clamped_end {
                break;
            }
            let maybe_val_pda = Account::<ValidatorPda>::try_from(acc_info);
            if let Ok(val_pda) = maybe_val_pda {
                msg!("ValidatorPda #{} => address: {}", i, val_pda.address);
            } else {
                msg!("ValidatorPda #{} => <unable to load validator PDA>", i);
            }
        }

        Ok(())
    }
    // ------------------------------------------------------------------
    //  4) Example: name / reward cooldown updates
    // ------------------------------------------------------------------

    pub fn update_player_name_cooldown(
        ctx: Context<UpdatePlayerNameCooldown>,
        new_name: String
    ) -> Result<()> {
        let pda = &mut ctx.accounts.player_pda;
        let clock = Clock::get()?;
        let now = clock.unix_timestamp;
        let one_week = 7 * 24 * 3600;

        require!(pda.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);

        if let Some(last_change) = pda.last_name_change {
            require!(now - last_change >= one_week, ErrorCode::NameChangeCooldown);
        }
        pda.name = new_name;
        pda.last_name_change = Some(now);
        Ok(())
    }

    pub fn update_player_reward_cooldown(
        ctx: Context<UpdatePlayerRewardCooldown>,
        new_reward: Pubkey
    ) -> Result<()> {
        let pda = &mut ctx.accounts.player_pda;
        let clock = Clock::get()?;
        let now = clock.unix_timestamp;
        let one_week = 7 * 24 * 3600;

        require!(pda.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);

        if let Some(last_change) = pda.last_reward_change {
            require!(now - last_change >= one_week, ErrorCode::NameChangeCooldown);
        }
        pda.reward_address = new_reward;
        pda.last_reward_change = Some(now);
        Ok(())
    }

    // ------------------------------------------------------------------
    //  5) Submit Minting List (example)
    // ------------------------------------------------------------------
    /// Demonstration of how to keep or remove this logic as you see fit.
    pub fn submit_minting_list(
        ctx: Context<SubmitMintingList>,
        game_number: u32,
        player_names: Vec<String>
    ) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let validator = &ctx.accounts.validator;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        // Check the game
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        // If we store "validators" in the game, check we are in that list, or remove this check
        // Example "old" code:
        // For a minimal approach, you might remove it or adapt to your new PDAs
        // We'll keep it for demonstration:
        // Suppose we want error if the validator isn't recognized by the game
         //Err(ErrorCode::ValidatorNotRegistered.into())?;
        // ...
        // You can do the rest or remove it entirely

        // For demonstration, just return Ok
        Ok(())
    }
}

//
// ------------------------------------------------------------------
// Accounts + PDAs
// ------------------------------------------------------------------

#[account]
pub struct DApp {
    pub owner: Pubkey,
    /// The total number of players across all games
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
    // Minimal leftover fields (optional):
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,

    // If you want to keep your "minting" logic, store:
    pub minting_agreements: Vec<MintingAgreement>,
}
impl Game {
    // Just approximate the space needed
    pub const LEN: usize = 8 + (4 + 4 + 1) + (4 + 64) + 9 + 9; 
    // ^ 20k of dynamic space if you plan to push "minting_agreements"
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct MintingAgreement {
    pub player_name: String,
    pub validators: Vec<Pubkey>,
}
#[derive(Accounts)]
pub struct GetPlayerListPdaPage<'info> {
    #[account(seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,
    // We'll read `dapp.global_player_count`, 
    // and the actual PDAs are in ctx.remaining_accounts.
}
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct GetValidatorListPdaPage<'info> {
    #[account(seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
    // We'll read `game.validator_count`.
    // The actual validator PDAs are in ctx.remaining_accounts.
}
#[account]
pub struct PlayerPda {
    pub name: String,
    pub authority: Pubkey,
    pub reward_address: Pubkey,
    pub last_name_change: Option<i64>,
    pub last_reward_change: Option<i64>,
}
impl PlayerPda {
    pub const LEN: usize = 8 + (4 + 32) + 32 + 32 + 9 + 9;
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
    // If you still want an older Player account for backward compatibility
    pub name: String,  
    pub address: Pubkey,
    pub reward_address: Pubkey,
    pub last_minted: Option<i64>,
    pub last_name_change: Option<i64>,
    pub last_reward_address_change: Option<i64>,
}
impl Player {
    pub const MAX_NAME_LEN: usize = 16;
    pub const LEN: usize = 4 + Self::MAX_NAME_LEN + 32 + 32 + 9 + 9 + 9;
}

//
// ------------------------------------------------------------------
// Accounts contexts for each instruction
// ------------------------------------------------------------------

#[derive(Accounts)]
pub struct InitializeDapp<'info> {
    #[account(
        init, 
        payer = user, 
        space = DApp::LEN, 
        seeds = [b"dapp"], 
        bump
    )]
    pub dapp: Account<'info, DApp>,

    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct GetValidatorList<'info> {
    #[account(seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,
}
#[derive(Accounts)]
pub struct RelinquishOwnership<'info> {
    #[account(mut, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,

    #[account(mut)]
    pub signer: Signer<'info>,
}

// Minimal
#[derive(Accounts)]
#[instruction(game_number: u32, description: String)]
pub struct InitializeGame<'info> {
    #[account(
        init,
        payer = user,
        space = Game::LEN,
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

/// Register a new validator for a game
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

/// Register a brand-new player as a PDA
#[derive(Accounts)]
pub struct RegisterPlayerPda<'info> {
    #[account(
        mut,
        seeds = [b"dapp"],
        bump
    )]
    pub dapp: Account<'info, DApp>,

    #[account(
        init,
        payer = user,
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

// Minimal
#[derive(Accounts)]
#[instruction(game_number: u32, player_names: Vec<String>)]
pub struct SubmitMintingList<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    pub validator: Signer<'info>,
}

// Name or reward cooldown updates
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

//
// [LEGACY] Some older instructions might remain if you want them
// e.g. RegisterPlayer (full-blown big game expansions)
// or the older minted code. Just keep or remove as you see fit.
//

//
// ------------------------------------------------------------------
// Errors
// ------------------------------------------------------------------
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
//
// ------------------------------------------------------------------
// Utility
// ------------------------------------------------------------------

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
    // no-op by default
    Ok(())
}

fn mint_tokens(
    _game: &mut Account<Game>,
    _address: &Pubkey,
    _amount: u64
) {
    // no-op or implement your logic
}

/// Example, if you still want to get validator info
pub fn get_validator_info(ctx: Context<GetValidatorList>, validator: Pubkey) -> Result<()> {
    let game = &ctx.accounts.game;
    let seed = game.last_seed.ok_or(ErrorCode::HashConversionError)?;
    let group_id = calculate_group_id(&validator, seed)?;
    emit!(ValidatorInfoEvent { seed, group_id });
    Ok(())
}

#[event]
pub struct ValidatorInfoEvent {
    pub seed: u64,
    pub group_id: u64,
}
