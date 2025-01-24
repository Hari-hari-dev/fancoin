use anchor_lang::prelude::*;
use anchor_spl::{
    associated_token::AssociatedToken,
    token::{self, Mint, Token, TokenAccount, MintTo},
};
use sha3::{Digest, Keccak256};
use std::convert::TryInto;
use std::collections::HashMap;
declare_id!("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut");

// --------------------------------------------------------------------
// Accounts + Data
// --------------------------------------------------------------------

#[account]
pub struct DApp {
    pub owner: Pubkey,
    pub global_player_count: u32,
    pub mint_pubkey: Pubkey, // store an SPL mint pubkey
}
impl DApp {
    pub const LEN: usize = 8 + 32 + 4 + 32;
}

#[account]
pub struct Game {
    pub game_number: u32,
    pub validator_count: u32,
    pub active_validator_count: u32, // New field to track active validators
    pub last_reset_hour: Option<u32>,  // Changed to Option<u32>
    pub status: u8,
    pub description: String,
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,
}
impl Game {
    pub const LEN: usize = 8
        + 4 // game_number
        + 4 // validator_count
        + 4 // active_validator_count
        + 5 // last_reset_hour (Option<u32>)
        + 1 // status
        + 64 // description
        + 8 // last_seed
        + 8; // last_punch_in_time
}

#[account]
pub struct PlayerPda {
    pub name: String,
    pub authority: Pubkey,
    pub reward_address: Pubkey,
    pub last_name_change: Option<i64>,
    pub last_reward_change: Option<i64>,
    pub partial_validators: Vec<Pubkey>,
    pub last_minted: Option<i64>,
}
impl PlayerPda {
    pub const MAX_PARTIAL_VALS: usize = 10;
    pub const LEN: usize = 8
        + (4 + 32) // name
        + 32 // authority
        + 32 // reward_address
        + 9 // last_name_change
        + 9 // last_reward_change
        + 4 + (Self::MAX_PARTIAL_VALS * 32) // partial_validators
        + 9; // last_minted
}

/// (NEW) A small account to store a name->PlayerPda reference, ensuring uniqueness.
#[account]
pub struct PlayerNamePda {
    /// The user-chosen name (up to 32 bytes, for example).
    pub name: String,
    /// The PDA that uses this name.
    pub player_pda: Pubkey,
}
impl PlayerNamePda {
    pub const MAX_NAME_LEN: usize = 32; // Adjust as needed
    pub const LEN: usize = 8 + (4 + Self::MAX_NAME_LEN) + 32; // 8 disc + name + pda
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
pub struct MintAuthority {
    pub bump: u8,
}

// --------------------------------------------------------------------
// Accounts
// --------------------------------------------------------------------

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

    #[account(
        mut,
        seeds = [b"validator", &game_number.to_le_bytes(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    #[account(mut)]
    pub validator: Signer<'info>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct RegisterValidatorPda<'info> {
    #[account(
        mut,
        seeds = [b"game", &game_number.to_le_bytes()],
        bump
    )]
    pub game: Account<'info, Game>,

    /// The same fancy mint used by the DApp
    #[account(mut, address = dapp.mint_pubkey)]
    pub fancy_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = user,
        space = ValidatorPda::LEN,
        seeds = [
            b"validator",
            &game_number.to_le_bytes()[..],
            user.key().as_ref()
        ],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    /// The user paying for creation of the validator + ATA (the “validator”).
    #[account(mut)]
    pub user: Signer<'info>,

    /// The ATA for (validator, fancy_mint), created if needed.
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = fancy_mint,
        associated_token::authority = user
    )]
    pub validator_ata: Account<'info, TokenAccount>,

    #[account(seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,

    #[account(address = token::ID)]
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn register_validator_pda(
    ctx: Context<RegisterValidatorPda>,
    game_number: u32,
) -> Result<()> {
    let game = &mut ctx.accounts.game;
    require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

    let val_pda = &mut ctx.accounts.validator_pda;
    val_pda.address = ctx.accounts.user.key();
    val_pda.last_activity = Clock::get()?.unix_timestamp;

    // Optionally store the ATA inside validator_pda if you want
    // val_pda.ata_address = ctx.accounts.validator_ata.key();

    game.validator_count += 1;
    game.active_validator_count += 1;
    msg!(
        "Registered validator => game={}, validator={}, ATA={}",
        game_number,
        val_pda.address,
        ctx.accounts.validator_ata.key()
    );
    Ok(())
}

/// (CHANGED) Updated RegisterPlayerPda to include `player_name_pda` in context
#[derive(Accounts)]
#[instruction(name: String)]
pub struct RegisterPlayerPda<'info> {
    /// The DApp. We read `dapp.mint_pubkey` to know which Mint to use.
    #[account(mut, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,

    /// The actual Mint account that must match dapp.mint_pubkey.
    #[account(constraint = fancy_mint.key() == dapp.mint_pubkey)]
    pub fancy_mint: Account<'info, Mint>,

    /// We initialize the PlayerPda (increment global_player_count).
    #[account(
        init_if_needed,
        payer = user,
        space = PlayerPda::LEN,
        seeds = [
            b"player_pda",
            &dapp.global_player_count.to_le_bytes()[..]
        ],
        bump
    )]
    pub player_pda: Account<'info, PlayerPda>,

    /// (NEW) The name-based PDA to enforce uniqueness.
    /// If `name.as_bytes()` is the same as another user’s, this init fails -> collision!
    #[account(
        init,
        payer = user,
        space = PlayerNamePda::LEN,
        seeds = [
            b"player_name",
            name.as_bytes()
        ],
        bump
    )]
    pub player_name_pda: Account<'info, PlayerNamePda>,

    /// The user paying for the creation of PlayerPda (and the ATA).
    #[account(mut)]
    pub user: Signer<'info>,

    /// We create an ATA for (user, fancy_mint) if needed.
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = fancy_mint,
        associated_token::authority = user
    )]
    pub user_ata: Account<'info, TokenAccount>,

    #[account(address = token::ID)]
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
#[instruction(game_number: u32)]
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

// --------------------------------------------------------------------
// *** SubmitMintingList ***
// --------------------------------------------------------------------

// -----------------------------------------------------------
#[derive(Accounts)]
#[instruction(game_number: u32, player_ids: Vec<u32>)]
pub struct SubmitMintingList<'info> {
    // Because we reference `game_number` in seeds, we must have `#[instruction]` above.
    #[account(
        mut,
        seeds = [b"game", &game_number.to_le_bytes()],
        bump
    )]
    pub game: Account<'info, Game>,

    #[account(
        mut,
        seeds = [b"validator", &game_number.to_le_bytes(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    pub validator: Signer<'info>,

    // For your SPL mint
    #[account(mut, address = dapp.mint_pubkey)]
    pub fancy_mint: Account<'info, Mint>,

    #[account(seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,

    #[account(
        seeds = [b"mint_authority"],
        bump = mint_authority.bump
    )]
    pub mint_authority: Account<'info, MintAuthority>,

    #[account(address = token::ID)]
    pub token_program: Program<'info, Token>,

    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
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
#[instruction(game_number: u32)]
pub struct ApprovePlayerMinting<'info> {
    #[account(seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    #[account(
        mut,
        seeds = [b"validator", &game_number.to_le_bytes(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

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

// 8) For initialize_mint
#[derive(Accounts)]
pub struct InitializeMint<'info> {
    #[account(mut)]
    pub dapp: Account<'info, DApp>,

    #[account(
        init,
        payer = payer,
        seeds = [b"mint_authority"],
        space = 8 + 1,
        bump
    )]
    pub mint_authority: Account<'info, MintAuthority>,

    #[account(
        init,
        payer = payer,
        seeds = [b"my_spl_mint"],
        bump,
        mint::decimals = 6,
        mint::authority = mint_authority,
        mint::freeze_authority = mint_authority
    )]
    pub mint_for_dapp: Account<'info, Mint>,

    #[account(mut)]
    pub payer: Signer<'info>,

    #[account(address = token::ID)]
    pub token_program: Program<'info, Token>,

    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

// --------------------------------------------------------------------
// The Program Module
// --------------------------------------------------------------------
#[program]
pub mod fancoin {
    use super::*;

    pub fn initialize_dapp(ctx: Context<InitializeDapp>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        dapp.owner = ctx.accounts.user.key();
        dapp.global_player_count = 0;
        dapp.mint_pubkey = Pubkey::default(); // Will be set during initialize_mint
        msg!("DApp initialized => owner={}", dapp.owner);
        Ok(())
    }

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
        game.active_validator_count = 0; // Initialize to zero
        game.last_reset_hour = None;      // Initialize to None
        game.last_seed = None;
        game.last_punch_in_time = None;
        msg!("Game #{} initialized => {}", game_number, game.description);
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
        game.description = description.clone();
        msg!(
            "Game #{} updated => status={} desc='{}'",
            game_number,
            new_status,
            description
        );
        Ok(())
    }

    pub fn punch_in(ctx: Context<PunchIn>, game_number: u32) -> Result<()> {
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let current_hour = (current_time / 3600) as u32;
        let current_minute = ((current_time % 3600) / 60) as u32;
        let game = &mut ctx.accounts.game;

        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        require!(game.status != 2, ErrorCode::GameIsBlacklisted);

        // Check if a new hour has started and if it's within the first 8 minutes
        if let Some(last_reset_hour) = game.last_reset_hour {
            if current_hour > last_reset_hour{
                game.active_validator_count = 0; // Reset active validators count
                game.last_reset_hour = Some(current_hour);
                msg!("Active validator count reset for new hour: {}", current_hour);
            }
        }
        // } else if current_minute > 8 {
        //     // Initialize last_reset_hour if it's the first punch_in
        //     msg!("Punch-in period over for this hour. {}", current_hour);
        //     //return Ok(());
        // }

        let validator_key = ctx.accounts.validator.key();
        let last_activity = ctx.accounts.validator_pda.last_activity;

        // Determine the hour of the last punch_in
        let validator_last_hour = if last_activity > 0 {
            (last_activity / 3600) as u32
        } else {
            0
        };

        // If the validator hasn't punched in this hour, increment active_validator_count
        if validator_last_hour < current_hour {
            if game.active_validator_count < game.validator_count {
                game.active_validator_count += 1;
                msg!(
                    "Validator {} marked as active for hour {}. Total active: {}",
                    validator_key,
                    current_hour,
                    game.active_validator_count
                );
            }
        }

        // Update last_activity timestamp
        ctx.accounts.validator_pda.last_activity = current_time;

        // Existing punch_in logic
        let mut hasher = Keccak256::new();
        hasher.update(validator_key.to_bytes());
        hasher.update(clock.slot.to_le_bytes());
        let hash_res = hasher.finalize();
        let seed = u64::from_le_bytes(
            hash_res[0..8].try_into().map_err(|_| ErrorCode::HashConversionError)?
        );
        game.last_seed = Some(seed);
        game.last_punch_in_time = Some(current_time);
        msg!("Punch in => seed={}, time={}", seed, current_time);
        Ok(())
    }

    /// Register a player with a unique name by initializing PlayerPda and PlayerNamePda
    pub fn register_player_pda(
        ctx: Context<RegisterPlayerPda>,
        name: String,
    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        let player = &mut ctx.accounts.player_pda;
        let name_pda = &mut ctx.accounts.player_name_pda;

        // (A) Enforce max name length
        require!(name.len() <= PlayerNamePda::MAX_NAME_LEN, ErrorCode::InvalidNameLength);

        // (B) Fill in PlayerPda
        player.name = name.clone();
        player.authority = ctx.accounts.user.key();
        player.reward_address = ctx.accounts.user_ata.key();
        player.last_name_change = None;
        player.last_reward_change = None;
        player.partial_validators = Vec::new();
        player.last_minted = None;

        // (C) Initialize PlayerNamePda data
        name_pda.name = name;
        name_pda.player_pda = player.key();

        // (D) Increment global_player_count
        dapp.global_player_count += 1;

        msg!(
            "Registered player => name='{}', authority={}, ATA={}, name_pda={}",
            player.name,
            player.authority,
            player.reward_address,
            name_pda.key()
        );
        Ok(())
    }

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
        game.active_validator_count += 1; // Increment active validators count
        msg!(
            "Registered validator => game={}, validator={}",
            game_number,
            val_pda.address
        );
        Ok(())
    }    
    pub fn submit_minting_list<'info>(
        ctx: Context<'_, '_, '_, 'info, SubmitMintingList<'info>>,
        game_number: u32,
        player_ids: Vec<u32>,
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        require!(
            ctx.accounts.validator_pda.address == ctx.accounts.validator.key(),
            ErrorCode::ValidatorNotRegistered
        );
    
        // 1) Build a quick map of leftover Pubkey => &AccountInfo
        use std::collections::HashMap;
        let leftover_map: HashMap<Pubkey, &AccountInfo> = ctx
            .remaining_accounts
            .iter()
            .map(|acc_info| (acc_info.key(), acc_info))
            .collect();
    
        // Time checks (unchanged)
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let current_minute = ((current_time % 3600) / 60) as u32;
        let current_hour = (current_time / 3600) as u32;
    
        let validator_last_activity = ctx.accounts.validator_pda.last_activity;
        let validator_last_hour = (validator_last_activity / 3600) as u32;
        if validator_last_hour != current_hour {
            msg!("Validator hasn't used punch_in this hour.");
            return Ok(());
        }
        if let Some(last_reset_hour) = game.last_reset_hour {
            if current_hour > last_reset_hour {
                msg!("punch_in hasn't been activated yet this hour.");
                return Ok(());
            }
        }
        if current_minute < 7 {
            msg!("Minting is blocked during the first 7 minutes of the hour.");
            return Ok(());
        }
    
        msg!("submit_minting_list => player_ids={:?}", player_ids);
        let total_vals = game.validator_count as usize;
        let active_vals = game.active_validator_count as usize;
        let total_groups = (total_vals + 3) / 4;
        let failover_tolerance = calculate_failover_tolerance(total_vals) as u64;
    
        // Keep leftover_iter for [PlayerPda, PlayerATA] pairs
        let mut leftover_iter = ctx.remaining_accounts.iter();
        let mut minted_count = 0_usize;
    
        for pid in player_ids {
            let seed = match game.last_seed {
                Some(s) => s,
                None => {
                    msg!("No last_seed => cannot finalize => pid={}", pid);
                    continue;
                }
            };
    
            // leftover => [PlayerPda, PlayerATA]
            let pda_accinfo = if let Some(acc) = leftover_iter.next() {
                acc.clone()
            } else {
                msg!("Not enough leftover => skip pid={}", pid);
                continue;
            };
            let ata_accinfo = if let Some(acc) = leftover_iter.next() {
                acc.clone()
            } else {
                msg!("Not enough leftover => skip pid={}", pid);
                continue;
            };
    
            // Load PlayerPda
            let mut player_pda = match Account::<PlayerPda>::try_from(&pda_accinfo) {
                Ok(x) => x,
                Err(_) => {
                    msg!("Cannot decode PlayerPda => pid={}", pid);
                    continue;
                }
            };
    
            // (A) Approve
            let val_key = ctx.accounts.validator.key();
            if !player_pda.partial_validators.contains(&val_key) {
                player_pda.partial_validators.push(val_key);
                msg!(
                    "Approved => player={} by validator={} => partial_validators.len={}",
                    player_pda.name,
                    val_key,
                    player_pda.partial_validators.len()
                );
            }
    
            // (B) Minting Condition based on active validators
            if (active_vals > 1 && player_pda.partial_validators.len() < 2)
                || (active_vals == 1 && player_pda.partial_validators.len() < 1)
            {
                msg!(
                    "Player {} => partial_validators.len()={} with active_vals={}. Skipping finalize.",
                    player_pda.name,
                    player_pda.partial_validators.len(),
                    active_vals
                );
                player_pda.try_serialize(&mut &mut pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
    
            // (C) Failover check
            let first_validator = player_pda.partial_validators[0];
            let first_gid = calculate_group_id_mod(&first_validator, seed, total_groups as u64)?;
            let mut all_same = true;
            for vk in player_pda.partial_validators.iter().skip(1) {
                let gid = calculate_group_id_mod(vk, seed, total_groups as u64)?;
                let dist = {
                    let direct_diff = if gid > first_gid { gid - first_gid } else { first_gid - gid };
                    let wrap_diff = total_groups as u64 - direct_diff;
                    direct_diff.min(wrap_diff)
                };
                if dist > failover_tolerance {
                    all_same = false;
                    break;
                }
            }
            if !all_same {
                msg!("Failover => remain => player={}", player_pda.name);
                player_pda.try_serialize(&mut &mut pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
    
            // (D) Time gating => optional
            let last_time = player_pda.last_minted.unwrap_or(0);
            let diff_seconds = current_time.saturating_sub(last_time);
            let diff_minutes = diff_seconds.max(0) as u64 / 60;
            let minted_amount = diff_minutes.saturating_mul(2_833_333);
                // if !(7..=34).contains(&diff_minutes) {
            //     msg!(
            //         "Outside 7..34 => no tokens => pid={}, diff_minutes={}",
            //         pid,
            //         diff_minutes
            //     );
            //     player_pda.last_minted = Some(current_time);
            //     player_pda.try_serialize(&mut &mut pda_accinfo.try_borrow_mut_data()?[..])?;
            //     continue;
            // }

            // (
            // (E) Player's ATA check
            // 1) Parse leftover as a TokenAccount
            if Account::<TokenAccount>::try_from(&ata_accinfo).is_err() {
                msg!("Leftover is NOT a valid TokenAccount => skipping pid={}", pid);
                player_pda.try_serialize(&mut &mut pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
            // 2) Confirm it matches the player's known reward_address
            if ata_accinfo.key() != player_pda.reward_address {
                msg!(
                    "Player ATA mismatch => leftover={:?} != stored={:?} => skipping pid={}",
                    ata_accinfo.key(),
                    player_pda.reward_address,
                    pid
                );
                player_pda.try_serialize(&mut &mut pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
    
            // Actually mint => player’s ATA
            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.fancy_mint.to_account_info(),
                        to: ata_accinfo,
                        authority: ctx.accounts.mint_authority.to_account_info(),
                    },
                    &[&[b"mint_authority", &[ctx.accounts.mint_authority.bump]]],
                ),
                minted_amount,
            )?;
    
            // Reward partial validators by minting to their ATAs
            use anchor_spl::associated_token::get_associated_token_address;
            for vk in &player_pda.partial_validators {
                let validator_ata_key = get_associated_token_address(vk, &ctx.accounts.fancy_mint.key());
                let Some(validator_ata_info) = leftover_map.get(&validator_ata_key) else {
                    msg!("Validator ATA not provided => skipping validator {}", vk);
                    continue;
                };
    
                let Ok(ata_account) = Account::<TokenAccount>::try_from(*validator_ata_info) else {
                    msg!("Validator ATA is not a valid TokenAccount => skipping validator {}", vk);
                    continue;
                };
    
                if ata_account.key() != validator_ata_key {
                    msg!("Validator ATA mismatch => skipping validator {}", vk);
                    continue;
                }
    
                token::mint_to(
                    CpiContext::new_with_signer(
                        ctx.accounts.token_program.to_account_info(),
                        MintTo {
                            mint: ctx.accounts.fancy_mint.to_account_info(),
                            to: ata_account.to_account_info(),
                            authority: ctx.accounts.mint_authority.to_account_info(),
                        },
                        &[&[b"mint_authority", &[ctx.accounts.mint_authority.bump]]],
                    ),
                    1_618_034, // Example amount
                )?;
            }
    
            // Update PlayerPda
            player_pda.partial_validators.clear();
            player_pda.last_minted = Some(current_time);
    
            msg!(
                "Minted {} => pid={}, partial_val_count=0, diff_minutes={}",
                minted_amount,
                pid,
                diff_minutes
            );
            minted_count += 1;
    
            // Serialize back
            player_pda.try_serialize(&mut &mut pda_accinfo.try_borrow_mut_data()?[..])?;
        }
    
        msg!("submit_minting_list => minted for {} players", minted_count);
        Ok(())
    }
    

    
    
    pub fn approve_player_minting(
        ctx: Context<ApprovePlayerMinting>,
        game_number: u32,
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);
        require!(
            ctx.accounts.validator_pda.address == ctx.accounts.validator.key(),
            ErrorCode::ValidatorNotRegistered
        );
        let player_pda = &mut ctx.accounts.player_pda;
        if !player_pda.partial_validators.contains(&ctx.accounts.validator.key()) {
            player_pda.partial_validators.push(ctx.accounts.validator.key());
        }
        msg!(
            "Approved player={} by validator={}. partial_validators.len={}",
            player_pda.name,
            ctx.accounts.validator.key(),
            player_pda.partial_validators.len()
        );
        Ok(())
    }

    pub fn finalize_player_minting(
        ctx: Context<FinalizePlayerMinting>,
        game_number: u32,
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        let player_pda = &mut ctx.accounts.player_pda;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        if player_pda.partial_validators.len() < 2 {
            msg!(
                "Player {} has only {} partial => skipping finalize",
                player_pda.name,
                player_pda.partial_validators.len()
            );
            return Ok(());
        }

        let seed = match game.last_seed {
            Some(s) => s,
            None => {
                msg!("No last_seed => cannot finalize.");
                return Ok(());
            }
        };
        let total_vals = game.validator_count as usize;
        let total_groups = (total_vals + 3) / 4;
        let fail_tolerance = calculate_failover_tolerance(total_vals) as u64;

        let first_validator = player_pda.partial_validators[0];
        let first_gid = calculate_group_id_mod(&first_validator, seed, total_groups as u64)?;
        let mut all_same = true;
        for vk in player_pda.partial_validators.iter().skip(1) {
            let gid = calculate_group_id_mod(vk, seed, total_groups as u64)?;
            let direct_diff =
                if gid > first_gid { gid - first_gid } else { first_gid - gid };
            let wrap_diff = total_groups as u64 - direct_diff;
            let dist = direct_diff.min(wrap_diff);
            if dist > fail_tolerance {
                all_same = false;
                break;
            }
        }
        if all_same {
            mint_tokens_for_player(&game, &player_pda.name, Clock::get()?.unix_timestamp)?;
            for vk in &player_pda.partial_validators {
                mint_tokens(&game, vk, 1_618_034);
            }
            player_pda.partial_validators.clear();
            msg!(
                "finalize => minted tokens => player={}, reward validators. Done.",
                player_pda.name
            );
        } else {
            msg!("Failover => remain => player={}", player_pda.name);
        }
        Ok(())
    }

    pub fn initialize_mint(ctx: Context<InitializeMint>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        dapp.mint_pubkey = ctx.accounts.mint_for_dapp.key();
        let bump = *ctx.bumps.get("mint_authority").unwrap();
        ctx.accounts.mint_authority.bump = bump;
        msg!("Mint created => pubkey={}", dapp.mint_pubkey);
        Ok(())
    }

    // (NEW) Reset active validators count; should be called at the start of each hour
    // pub fn reset_active_validators(
    //     ctx: Context<ResetActiveValidators>,
    //     game_number: u32,
    // ) -> Result<()> {
    //     let game = &mut ctx.accounts.game;
    //     require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

    //     game.active_validator_count = 0; // Reset active validators count
    //     game.last_reset_hour = Some((Clock::get()?.unix_timestamp / 3600) as u32); // Update last_reset_hour
    //     msg!("Active validator count reset to 0 for game {}", game_number);
    //     Ok(())
    // }
}

// --------------------------------------------------------------------
//  Utility + Errors
// --------------------------------------------------------------------
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
    #[msg("Account already exists.")]
    AccountAlreadyExists,
    #[msg("Invalid name length.")]
    InvalidNameLength,
}

/// We compute failover_tolerance as the # of digits in (validator_count+3)/4
pub fn calculate_failover_tolerance(total_validators: usize) -> usize {
    ((total_validators + 3) / 4)
        .to_string()
        .len()
}

/// Use keccak(address, seed) % total_groups => group
pub fn calculate_group_id_mod(address: &Pubkey, seed: u64, total_groups: u64) -> Result<u64> {
    let mut hasher = Keccak256::new();
    hasher.update(address.to_bytes());
    hasher.update(seed.to_le_bytes());
    let result = hasher.finalize();
    let bytes: [u8; 8] = result[0..8]
        .try_into()
        .map_err(|_| ErrorCode::HashConversionError)?;
    let raw_64 = u64::from_be_bytes(bytes);
    Ok(if total_groups > 0 { raw_64 % total_groups } else { 0 })
}

/// A simple placeholder for finalizing tokens.
pub fn mint_tokens_for_player(_game: &Account<Game>, player_name: &str, current_time: i64) -> Result<()> {
    let last_time = 0i64;
    let diff_seconds = current_time.saturating_sub(last_time);
    let diff_minutes = diff_seconds.max(0) as u64 / 60;

    if !(7..=34).contains(&diff_minutes) {
        msg!("No tokens => outside 7..34 => player={}", player_name);
        return Ok(());
    }
    let minted_amount = diff_minutes.saturating_mul(2_833_333);
    msg!(
        "SPL minted {} microtokens => player='{}' diff_minutes={}",
        minted_amount,
        player_name,
        diff_minutes
    );
    Ok(())
}

/// Another placeholder for awarding partial validators
pub fn mint_tokens(_game: &Account<Game>, _address: &Pubkey, _amount: u64) {
    // Placeholder for awarding partial validators
}
