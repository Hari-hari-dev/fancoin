use anchor_lang::prelude::*;
use anchor_lang::system_program;
use anchor_spl::{
    associated_token::AssociatedToken,
    token::{self, Mint, MintTo, Token, TokenAccount},
};
use sha3::{Digest, Keccak256};
use std::convert::TryInto;

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
    pub status: u8,
    pub description: String,
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,
}
impl Game {
    pub const LEN: usize = 8 + (4 + 4 + 1) + (4 + 64) + 9 + 9;
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
        + (4 + 32)
        + 32
        + 32
        + 9
        + 9
        + 4 + (Self::MAX_PARTIAL_VALS * 32)
        + 9;
}

/// A small account to store a name->PlayerPda reference, ensuring uniqueness.
#[account]
pub struct PlayerNamePda {
    /// The user-chosen name (up to 32 bytes).
    pub name: String,
    /// The PDA that uses this name.
    pub player_pda: Pubkey,
}
impl PlayerNamePda {
    pub const MAX_NAME_LEN: usize = 32;
    pub const LEN: usize = 8 + (4 + Self::MAX_NAME_LEN) + 32;  
}

#[account]
pub struct ValidatorPda {
    pub address: Pubkey,
    pub last_activity: i64,
    // (NEW) Track the last time this validator minted tokens or was made ineligible
    pub last_minted: Option<i64>,
}
impl ValidatorPda {
    // 8 disc + 32 pubkey + 8 i64 + 9 (Option<i64>) = 57
    pub const LEN: usize = 8 + 32 + 8 + 9;
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

    #[account(mut)]
    pub user: Signer<'info>,

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

/// Register a player with a unique name by initializing PlayerPda and PlayerNamePda
#[derive(Accounts)]
#[instruction(name: String)]
pub struct RegisterPlayerPda<'info> {
    #[account(mut, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,

    #[account(constraint = fancy_mint.key() == dapp.mint_pubkey)]
    pub fancy_mint: Account<'info, Mint>,

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

    #[account(mut)]
    pub user: Signer<'info>,

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
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct SubmitMintingList<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    #[account(
        mut,
        seeds = [b"validator", &game_number.to_le_bytes(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    pub validator: Signer<'info>,

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

/// (NEW) For initialize_mint
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
        msg!("Punch in => seed={}, time={}", seed, current_time);
        Ok(())
    }

    /// Register a player with a unique name by initializing PlayerPda + PlayerNamePda
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
        val_pda.last_minted = None; // new

        game.validator_count += 1;
        msg!(
            "Registered validator => game={}, validator={}, ATA={}",
            game_number,
            val_pda.address,
            ctx.accounts.validator_ata.key()
        );
        Ok(())
    }

    /// The main multi-player mint function
    /// (We do *NOT* mint to validators here. Instead, we simply set val_pda.last_minted = now.)
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
    
        msg!("submit_minting_list => player_ids={:?}", player_ids);
        let current_time = Clock::get()?.unix_timestamp;
        let total_vals = game.validator_count as usize;
        let total_groups = (total_vals + 3) / 4;
        let failover_tolerance = calculate_failover_tolerance(total_vals) as u64;
    
        // We'll always have the single validator's own PDA
        let val_pda = &mut ctx.accounts.validator_pda;
    
        // For each pid, we do our usual leftover approach
        let mut leftover_iter = ctx.remaining_accounts.iter();
        let mut minted_count = 0_usize;
    
        for pid in player_ids {
            let Some(seed) = game.last_seed else {
                msg!("No last_seed => cannot finalize => pid={}", pid);
                continue;
            };
    
            // leftover => [PlayerPda, PlayerATA]
            let Some(player_pda_accinfo) = leftover_iter.next() else {
                msg!("Not enough leftover => skip pid={}", pid);
                continue;
            };
            let Some(player_ata_accinfo) = leftover_iter.next() else {
                msg!("Not enough leftover => skip pid={}", pid);
                continue;
            };
    
            // Attempt to load PlayerPda
            let mut player_pda = match Account::<PlayerPda>::try_from(&player_pda_accinfo) {
                Ok(x) => x,
                Err(_) => {
                    msg!("Cannot decode PlayerPda => pid={}", pid);
                    continue;
                }
            };
    
            // (A) Approve: Add *this* validator if not already in partial_validators
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
    
            // (B) If partial_validators < 2 => skip
            if player_pda.partial_validators.len() < 2 {
                msg!(
                    "Player {} => only {} partial => skip finalize",
                    player_pda.name,
                    player_pda.partial_validators.len()
                );
                // Save partial_validators changes
                player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
    
            // (C) Failover check
            let first_validator = player_pda.partial_validators[0];
            let first_gid = calculate_group_id_mod(&first_validator, seed, total_groups as u64)?;
            let mut all_same = true;
            for vk in player_pda.partial_validators.iter().skip(1) {
                let gid = calculate_group_id_mod(vk, seed, total_groups as u64)?;
                let direct_diff = if gid > first_gid { gid - first_gid } else { first_gid - gid };
                let wrap_diff = total_groups as u64 - direct_diff;
                let dist = direct_diff.min(wrap_diff);
                if dist > failover_tolerance {
                    all_same = false;
                    break;
                }
            }
            if !all_same {
                msg!("Failover => remain => player={}", player_pda.name);
                player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
    
            // (D) Time gating => 7..34 minutes
            let last_time = player_pda.last_minted.unwrap_or(0);
            let diff_seconds = current_time.saturating_sub(last_time);
            let diff_minutes = diff_seconds.max(0) as u64 / 60;
            if !(1..=34).contains(&diff_minutes) {
                msg!(
                    "Outside 1..34 => no tokens => pid={}, diff_minutes={}",
                    pid,
                    diff_minutes
                );
                player_pda.last_minted = Some(current_time);
                player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
    
            // (E) Actually mint to player's ATA
            let minted_amount = diff_minutes.saturating_mul(2_833_333);
            let is_ata_ok = Account::<TokenAccount>::try_from(&player_ata_accinfo).is_ok();
            if !is_ata_ok {
                msg!("Leftover is NOT a valid TokenAccount => skip pid={}", pid);
                player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
    
            // CPI to mint
            let bump = ctx.accounts.mint_authority.bump;
            let seeds_auth: &[&[u8]] = &[b"mint_authority".as_ref(), &[bump]];
            let signer_seeds = &[&seeds_auth[..]];
            let cpi_ctx = CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.fancy_mint.to_account_info(),
                    to: player_ata_accinfo.to_account_info(),
                    authority: ctx.accounts.mint_authority.to_account_info(),
                },
                signer_seeds,
            );
            token::mint_to(cpi_ctx, minted_amount)?;
    
            msg!("Minted {} => pid={}", minted_amount, pid);
    
            // (F) Mark *this* validator (the signer) as minted now
            val_pda.last_minted = Some(current_time);
    
            // Clear partial_validators, store changes in PlayerPda
            player_pda.partial_validators.clear();
            player_pda.last_minted = Some(current_time);
            player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
    
            minted_count += 1;
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

        let Some(seed) = game.last_seed else {
            msg!("No last_seed => cannot finalize");
            return Ok(());
        };
        let total_vals = game.validator_count as usize;
        let total_groups = (total_vals + 3) / 4;
        let fail_tolerance = calculate_failover_tolerance(total_vals) as u64;

        let first_validator = player_pda.partial_validators[0];
        let first_gid = calculate_group_id_mod(&first_validator, seed, total_groups as u64)?;
        let mut all_same = true;
        for vk in player_pda.partial_validators.iter().skip(1) {
            let gid = calculate_group_id_mod(vk, seed, total_groups as u64)?;
            let direct_diff = if gid > first_gid { gid - first_gid } else { first_gid - gid };
            let wrap_diff = total_groups as u64 - direct_diff;
            let dist = direct_diff.min(wrap_diff);
            if dist > fail_tolerance {
                all_same = false;
                break;
            }
        }

        if all_same {
            // Actually do your final mint to player, etc.
            mint_tokens_for_player(&game, &player_pda.name, Clock::get()?.unix_timestamp)?;
            for vk in &player_pda.partial_validators {
                // In the old code, we minted for validators here. Now we do the same approach:
                update_validator_mint_time(vk, game_number, Clock::get()?.unix_timestamp)?;
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

    /// (NEW) The function for validators to claim up to 1 hour of tokens at 0.02857/min
    pub fn claim_validator_reward(
        ctx: Context<ClaimValidatorReward>,
        game_number: u32,
    ) -> Result<()> {
        let val_pda = &mut ctx.accounts.validator_pda;
        require!(
            val_pda.address == ctx.accounts.validator.key(),
            ErrorCode::ValidatorNotRegistered
        );

        let current_time = Clock::get()?.unix_timestamp;
        let last_time = val_pda.last_minted.unwrap_or(0);

        // 1) Compute how many minutes since last minted
        let diff_seconds = current_time.saturating_sub(last_time);
        let diff_minutes = diff_seconds.max(0) as u64 / 60;

        // 2) Cap it at 60 => 1 hour max
        let minutes_capped = diff_minutes.min(60);
        if minutes_capped == 0 {
            msg!("No reward => last_minted was too recent");
            return Ok(());
        }

        // 3) 0.02857 tokens per minute
        let ratio = 0.02857_f64;
        let reward_f64 = minutes_capped as f64 * ratio;
        let reward_u64 = reward_f64 as u64; // truncated

        if reward_u64 == 0 {
            msg!("Truncated to 0 => no reward => skipping");
            return Ok(());
        }

        // 4) Mint to validator ATA
        let bump = ctx.accounts.mint_authority.bump;
        let seeds_auth: &[&[u8]] = &[b"mint_authority".as_ref(), &[bump]];
        let signer_seeds = &[&seeds_auth[..]];

        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: ctx.accounts.fancy_mint.to_account_info(),
                to: ctx.accounts.validator_ata.to_account_info(),
                authority: ctx.accounts.mint_authority.to_account_info(),
            },
            signer_seeds,
        );
        token::mint_to(cpi_ctx, reward_u64)?;

        // 5) Update last_minted => resets the timer
        val_pda.last_minted = Some(current_time);

        msg!(
            "Claimed {} tokens => validator={} after {} minutes (capped at 60)",
            reward_u64,
            val_pda.address,
            diff_minutes
        );

        Ok(())
    }
}

// --------------------------------------------------------------------
//  Additional Accounts for claim_validator_reward
// --------------------------------------------------------------------
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct ClaimValidatorReward<'info> {
    #[account(
        mut,
        seeds = [b"validator", &game_number.to_le_bytes(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    #[account(mut)]
    pub validator: Signer<'info>,

    #[account(mut)]
    pub validator_ata: Account<'info, TokenAccount>,

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

    pub system_program: Program<'info, System>,
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
fn calculate_failover_tolerance(total_validators: usize) -> usize {
    ((total_validators + 3) / 4)
        .to_string()
        .len()
}

/// Use keccak(address, seed) % total_groups => group
fn calculate_group_id_mod(address: &Pubkey, seed: u64, total_groups: u64) -> Result<u64> {
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
fn mint_tokens_for_player(_game: &Account<Game>, player_name: &str, current_time: i64) -> Result<()> {
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

// Just a placeholder if you're re-deriving + loading the validator PDE 
// in `submit_minting_list`:
fn update_validator_mint_time(
    _validator_key: &Pubkey,
    _game_number: u32,
    _current_time: i64,
) -> Result<()> {
    // In reality you'd do leftover or map logic, then:
    // val_pda.last_minted = Some(_current_time);
    // val_pda.serialize back
    Ok(())
}
