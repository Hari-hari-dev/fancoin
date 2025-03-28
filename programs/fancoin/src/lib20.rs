use anchor_lang::prelude::*;
use anchor_lang::prelude::InterfaceAccount;
use anchor_lang::system_program;
use anchor_spl::{
    token_2022::{self as token_2022, mint_to, ID as TOKEN_2022_PROGRAM_ID},
    // The 2022 account interfaces:
    //token_interface::{Mint, MintTo, Account as TokenAccount, Token2022 as Token},
};
//use anchor_spl::token_2022::TokenAccount;
//use spl_token_2022::state::Account as TokenAccount2022;
use anchor_spl::token_interface::{
    //Account as TokenAccount2022,//GenericTokenAccount as TokenAccount,
    Mint,
    Token2022,       // The “program” type for your token_program field
};
use anchor_spl::token_interface::TokenAccount;

use solana_gateway::Gateway;

use anchor_spl::token_2022::MintTo;
//use anchor_spl::token_2022::Account;
use anchor_spl::associated_token::AssociatedToken;
use sha3::{Digest, Keccak256};
use std::convert::TryInto;

declare_id!("B2K4GmpB86BH5npaZrDsN5kt9TRv48ajeUBbc3tFd2V1");

// --------------------------------------------------------------------
// Accounts + Data
// --------------------------------------------------------------------


#[account]
pub struct Dapp {
    pub player_count: u32,
    //pub dapp_number: u32,
    pub validator_count: u32,
    pub active_validator_count: u32, // New field to track active validators
    pub last_reset_hour: Option<u32>,  // Changed to Option<u32>
    pub description: String,
    pub socials: String,
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,
    pub mint_pubkey: Pubkey,
        // NEW FIELDS:
    /// Commission address (the ATA or any account receiving commission).
    pub commission_ata: Pubkey,  
    /// Commission percent (e.g. 20 => 20%).
    pub commission_percent: u16,
    /// Rate at which tokens are issued to players (e.g. 2_833_333).
    pub coin_issuance_rate: u64,
    /// Rate at which validators can claim (e.g. 28_570).
    pub validator_claim_rate: u64,
    /// Whether validators must be “curated” or can freely register.
    pub curated_val: bool,
    pub owner: Pubkey,
    pub claim_rate_lock: bool,
    pub coin_issuance_rate_lock: bool,
    pub commission_percent_lock: bool,
    pub gatekeeper_network: Pubkey,
    pub player_limit: u32,


}
impl Dapp {
    pub const LEN: usize = 340;
        // + 4 // player_count
        // + 4 // validator_count
        // + 4 // active_validator_count
        // + 5 // last_reset_hour (Option<u32>)
        // + (4 + 64) // description
        // + (4 + 64) // socials
        // + 9 // last_seed
        // + 9 // last_punch_in_time
        // + 33 // mint_pubkey
        // + 33                           // commission_ata
        // + 3                            // commission_percent (u16)
        // + 8                            // coin_issuance_rate (u64)
        // + 8                            // validator_claim_rate (u64)
        // + 2 
        // + 33
        // + 2
        // + 2
        // + 2
        // + 33      // owner
        // + 4 // <-- add 4 bytes for player_limit
        // + 8;

  
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
    pub pending_claim_ts: Option<i64>,       // when user requested a claim
    pub pending_game_time_ms: Option<i64>,   // new season time from the user’s API call
    pub pending_paid: bool,                  // if the pending claim has already been minted
    pub last_claim_ts: Option<i64>,          // last time we minted a final claim
}
impl PlayerPda {
    pub const MAX_PARTIAL_VALS: usize = 4;
    pub const LEN: usize = 295;
        // + (4 + 32)
        // + 32
        // + 32
        // + 9
        // + 9
        // + 4 + (Self::MAX_PARTIAL_VALS * 32)
        // + 9
        // + 9
        // + 9
        // + 2
        // + 9;
}

/// A small account to store a name->PlayerPda reference, ensuring uniqueness.
#[account]
pub struct PlayerNamePda {
    /// The user-chosen name (up to 32 bytes).
    pub name: String,
    /// The PDA that uses this name.
    pub player_pda: Pubkey,
    pub active: bool,
}
impl PlayerNamePda {
    pub const MAX_NAME_LEN: usize = 30;
    pub const LEN: usize = 75; // + (4 + Self::MAX_NAME_LEN + 8) + 32 + 2;  
}

#[account]
pub struct ValidatorPda {
    pub address: Pubkey,
    pub last_activity: i64,
    // (NEW) Track the last time this validator minted tokens or was made ineligible
    pub last_minted: Option<i64>,
    pub last_claimed: Option<i64>,
    // 3 levels of authority variable
}
impl ValidatorPda {
    // 8 disc + 32 pubkey + 8 i64 + 9 (Option<i64>) = 57
    pub const LEN: usize = 66;
    //8 + 32 + 8 + 9 + 9;
}




#[account]
pub struct MintAuthority {
    pub bump: u8,
}
impl MintAuthority {
    pub const LEN: usize = 9;
}

#[account]
pub struct WalletPda {
    pub wallet: Pubkey,
    pub is_registered: bool,
}

impl WalletPda {
    pub const LEN: usize = 8 + 32 + 1;
}
// --------------------------------------------------------------------
// Accounts
// --------------------------------------------------------------------


#[derive(Accounts)]
pub struct RelinquishOwnership<'info> {
    // #[account(mut, seeds = [b"dapp"], bump)]
    // pub dapp: Account<'info, DApp>,
    #[account(mut)]
    pub signer: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey)]
pub struct PunchIn<'info> {
    #[account(
        mut,
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    // ♦ Replacing &dapp_number.to_le_bytes() in the Validator seed
    #[account(
        mut,
        seeds = [b"validator", mint_pubkey.as_ref(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,
    pub gateway_token: UncheckedAccount<'info>,
    #[account(mut)]
    pub validator: Signer<'info>,
    pub system_program: Program<'info, System>,
}
// #[derive(Accounts)]
// #[instruction(mint_pubkey: Pubkey)]
// pub struct RegisterValidatorPda<'info> {
//     #[account(
//         mut,
//         seeds = [b"dapp", mint_pubkey.as_ref()],
//         bump
//     )]
//     pub dapp: Account<'info, Dapp>,

//     #[account(mut, constraint = fancy_mint.key() == dapp.mint_pubkey)]
//     pub fancy_mint: InterfaceAccount<'info, Mint>,

//     #[account(
//         init,
//         payer = user,
//         space = ValidatorPda::LEN,
//         seeds = [
//             b"validator",
//             mint_pubkey.as_ref(),
//             user.key().as_ref()
//         ],
//         bump
//     )]
//     pub validator_pda: Account<'info, ValidatorPda>,


//     #[account(mut)]
//     pub user: Signer<'info>,

//     #[account(
//         init_if_needed,
//         payer = user,
//         associated_token::mint = fancy_mint,
//         associated_token::authority = user
//     )]
//     pub validator_ata: InterfaceAccount<'info, TokenAccount>,
//     pub gateway_token: UncheckedAccount<'info>,

//     // #[account(seeds = [b"dapp"], bump)]
//     // pub dapp: Account<'info, DApp>,

//     #[account(address = TOKEN_2022_PROGRAM_ID)]  // Changed from `token::ID` to `spl_token_2022::ID`
//     pub token_program: Program<'info, Token2022>,
//     pub associated_token_program: Program<'info, AssociatedToken>,
//     pub system_program: Program<'info, System>,
//     pub rent: Sysvar<'info, Rent>,
// }
#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey)]
pub struct CreateUserAtaIfNeeded<'info> {
    /// The user who wants an ATA
    /// 
    // #[account(mut, seeds = [b"dapp"], bump)]
    // pub dapp: Account<'info, DApp>,
    #[account(mut)]
    pub user: Signer<'info>,

    /// The mint for which we want an ATA
    #[account(mut, constraint = fancy_mint.key() == dapp.mint_pubkey)]
    pub fancy_mint: InterfaceAccount<'info, Mint>,

    /// The Dapp (we only need this if you want to anchor an address check)
    #[account(seeds = [b"dapp", mint_pubkey.as_ref()], bump)]
    pub dapp: Account<'info, Dapp>,
    pub gateway_token: UncheckedAccount<'info>,
    /// The derived user’s ATA
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = fancy_mint,
        associated_token::authority = user
    )]
    pub user_ata: InterfaceAccount<'info, TokenAccount>,
    #[account(
        init_if_needed,
        payer = user,
        space = WalletPda::LEN,
        seeds = [
            b"wallet_pda",
            mint_pubkey.as_ref(),
            user.key().as_ref()
        ],
        bump
    )]
    pub wallet_pda: Account<'info, WalletPda>,
    // Programs
    #[account(address = TOKEN_2022_PROGRAM_ID)]
    pub token_program: Program<'info, Token2022>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}
#[derive(Accounts)]
pub struct UpdateCommissionInfo<'info> {
    #[account(
        mut,
        has_one = owner @ErrorCode::Unauthorized, // must match the dapp.owner
    )]
    pub dapp: Account<'info, Dapp>,

    /// The current owner must sign
    #[account(mut)]
    pub owner: Signer<'info>,
}

/// Register a player with a unique name by initializing PlayerPda and PlayerNamePda
#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey, name: String)]
pub struct RegisterPlayerPda<'info> {
    // #[account(mut, seeds = [b"dapp"], bump)]
    // pub dapp: Account<'info, DApp>,
    #[account(
        mut,
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,
    
    #[account(mut, constraint = fancy_mint.key() == dapp.mint_pubkey)]
    pub fancy_mint: InterfaceAccount<'info, Mint>,

    #[account(
        init_if_needed,
        payer = user,
        space = PlayerPda::LEN,
        seeds = [
            b"player_pda",
            dapp.key().as_ref(),
            &dapp.player_count.to_le_bytes()
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
            dapp.key().as_ref(),
            name.as_bytes()
        ],
        bump
    )]
    pub player_name_pda: Account<'info, PlayerNamePda>,
    pub gateway_token: UncheckedAccount<'info>,
    #[account(mut)]
    pub user: Signer<'info>,

    #[account(address = TOKEN_2022_PROGRAM_ID)]  // Changed from `token::ID` to `spl_token_2022::ID`
    pub token_program: Program<'info, Token2022>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

// --------------------------------------------------------------------
// *** SubmitMintingList ***
// --------------------------------------------------------------------
#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey)]
pub struct SubmitMintingList<'info> {
    #[account(
        mut,
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    #[account(
        mut,
        seeds = [b"validator", mint_pubkey.as_ref(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    pub validator: Signer<'info>,

    #[account(mut, constraint = fancy_mint.key() == dapp.mint_pubkey)]
    pub fancy_mint: InterfaceAccount<'info, Mint>,

    // #[account(seeds = [b"dapp"], bump)]
    // pub dapp: Account<'info, DApp>,
    pub gateway_token: UncheckedAccount<'info>,
    #[account(
        seeds = [b"mint_authority"],
        bump = mint_authority.bump
    )]
    pub mint_authority: Account<'info, MintAuthority>,

    #[account(address = TOKEN_2022_PROGRAM_ID)]  // Changed from `token::ID` to `spl_token_2022::ID`
    pub token_program: Program<'info, Token2022>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
}


#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey, new_name: String)]
pub struct UpdatePlayerNameCooldown<'info> {
    /// The PlayerPda being updated
    
    #[account(mut)]
    pub player_pda: Account<'info, PlayerPda>,

    /// The authority must match `player_pda.authority`
    #[account(mut)]
    pub user: Signer<'info>,

    /// The old PlayerNamePda => based on the “old” name 
    /// We pass `player_pda.name.as_bytes()` as the seed.
    #[account(
        mut,
        seeds = [
            b"player_name",
            dapp.key().as_ref(),
            player_pda.name.as_bytes(),
        ],
        bump,
    )]
    pub old_name_pda: Account<'info, PlayerNamePda>,

    /// The new name => we can either init or re-init (depending on whether 
    /// you want to create it fresh or fail if it already existed). 
    /// We show “init” for demonstration.
    #[account(
        init,
        payer = user,
        space = PlayerNamePda::LEN,
        seeds = [
            b"player_name",
            dapp.key().as_ref(),
            new_name.as_bytes(),
        ],
        bump
    )]
    pub new_name_pda: Account<'info, PlayerNamePda>,
    pub gateway_token: UncheckedAccount<'info>,
    /// If you want to verify the dapp 
    /// (not strictly necessary if you don’t do cross-checking).
    #[account(
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    #[account(address = system_program::ID)]
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdatePlayerRewardCooldown<'info> {
    #[account(mut)]
    pub player_pda: Account<'info, PlayerPda>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub gateway_token: UncheckedAccount<'info>,
}

#[derive(Accounts)]
pub struct TransferOwnership<'info> {
    #[account(
        mut,
        has_one = owner @ ErrorCode::Unauthorized
    )]
    pub dapp: Account<'info, Dapp>,

    #[account(mut)]
    pub owner: Signer<'info>,
}
#[derive(Accounts)]
#[instruction(
    description: String,
    socials: String,
    commission_percent: u16,
    coin_issuance_rate: u64,
    validator_claim_rate: u64,
    curated_val: bool,
    initial_commission_tokens: u64,
)]
pub struct InitializeDappAndMint<'info> {

    #[account(
        init,
        payer = user,
        space = Dapp::LEN,
        seeds = [b"dapp", mint_for_dapp.key().as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    #[account(
        init,
        payer = user,
        space = MintAuthority::LEN, // Enough for MintAuthority
        seeds = [b"mint_authority"],
        bump
    )]
    pub mint_authority: Account<'info, MintAuthority>,

    #[account(
        init,
        payer = user,
        seeds = [b"my_spl_mint", user.key().as_ref()],
        // or pass description as well if needed
        bump,
        mint::decimals = 6,
        mint::authority = mint_authority,
        //mint::freeze_authority = mint_authority
    )]
    pub mint_for_dapp: InterfaceAccount<'info, Mint>,

    // The user paying for everything.
    #[account(mut)]
    pub user: Signer<'info>,

    /// We'll auto-create a "commission_ata" by init_if_needed
    /// for the same user authority. 
    #[account(
        init_if_needed,
        payer = user,
        associated_token::mint = mint_for_dapp,
        associated_token::authority = user // or use some other "owner" if desired
    )]
    pub commission_ata: InterfaceAccount<'info, TokenAccount>,

    #[account(address = TOKEN_2022_PROGRAM_ID)]
    pub token_program: Program<'info, Token2022>,

    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}


#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey, validator_to_add: Pubkey)]
pub struct RegisterValidatorCurated<'info> {
    // (1) The Dapp account
    #[account(
        mut,
        has_one = owner @ ErrorCode::Unauthorized,
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    // (2) The dapp owner who pays for creating validator_pda + the ATA
    #[account(mut)]
    pub owner: Signer<'info>,

    // (3) The validator_pda. Seeds are [b"validator", mint_pubkey, validator_to_add]
    #[account(
        init,
        payer = owner,
        space = ValidatorPda::LEN,
        seeds = [
            b"validator",
            mint_pubkey.as_ref(),
            validator_to_add.as_ref()
        ],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    // (4) Must match dapp.mint_pubkey
    #[account(
        mut,
        constraint = fancy_mint.key() == dapp.mint_pubkey
    )]
    pub fancy_mint: InterfaceAccount<'info, Mint>,

    // (5) The validator’s real wallet => must match `validator_to_add`
    #[account(
        mut,
        address = validator_to_add
    )]
    pub new_validator: SystemAccount<'info>,
    // or `UncheckedAccount<'info>` if you don’t require it be a SystemAccount
    // pub gateway_token: UncheckedAccount<'info>,
    // (6) The ATA belonging to `new_validator` 
    // Because we do init_if_needed, Anchor normally also needs "rent" + "system_program" + 
    // "associated_token_program" + "token_program" in the struct. We'll keep them, except "rent".
    #[account(
        init_if_needed,
        payer = owner,
        associated_token::mint = fancy_mint,
        associated_token::authority = new_validator
    )]
    pub validator_ata: InterfaceAccount<'info, TokenAccount>,

    // (7) Program references
    #[account(address = token_2022::ID)]
    pub token_program: Program<'info, Token2022>,

    pub associated_token_program: Program<'info, AssociatedToken>,

    pub system_program: Program<'info, System>,

    // IMPORTANT: We REMOVED the line: `pub rent: Sysvar<'info, Rent>,`
    // so "rent" is no longer in the named fields. We'll parse it from leftover.
}

#[derive(Accounts)]
pub struct LockField<'info> {
    // The dapp must belong to the signer
    #[account(
        mut,
        has_one = owner @ ErrorCode::Unauthorized
    )]
    pub dapp: Account<'info, Dapp>,

    pub owner: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey, name: String)]
pub struct RequestClaim<'info> {
    /// The Dapp => ensures we’re referencing the correct dapp (and mint).
    #[account(
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    /// The PlayerNamePda => ensures we’re referencing the correct name for the dapp.
    #[account(
        seeds = [
            b"player_name",
            dapp.key().as_ref(),
            name.as_bytes()
        ],
        bump,
        // Optionally, require that it's still active:
        // constraint = player_name_pda.active == true,
    )]
    pub player_name_pda: Account<'info, PlayerNamePda>,

    /// The actual PlayerPda => we do NOT derive from seeds here, 
    /// but instead do `address = player_name_pda.player_pda`.
    #[account(
        mut,
        address = player_name_pda.player_pda,
        // Optionally use has_one = user => only if your PlayerPda has field `authority: Pubkey`.
        // If you prefer a manual check in the handler, remove this line and do `require!()`.
        // has_one = user @ ErrorCode::Unauthorized,
    )]
    pub player_pda: Account<'info, PlayerPda>,
    pub gateway_token: UncheckedAccount<'info>,
    /// The user that must match `player_pda.authority`.
    #[account(mut)]
    pub user: Signer<'info>,

    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey, name: String, new_time_seconds: u64)]
pub struct ValidatePlayerPubgTimeSlim<'info> {
    /// The Dapp => keep so we can read coin_issuance_rate etc. 
    #[account(
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    /// The validator who signs
    #[account(mut)]
    pub validator: Signer<'info>,
    #[account(address = token_2022::ID)]
    pub token_program: Program<'info, Token2022>,

    /// Required so we can call Clock::get() or do cross-program checks
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey, name: String, user_authority: Pubkey)]
pub struct RegisterPlayerPdaByValidator<'info> {
    #[account(
        mut,
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    #[account(mut)]
    pub validator: Signer<'info>,

    #[account(init, 
        payer = validator,
        space = PlayerPda::LEN,
        seeds = [
            b"player_pda",
            dapp.key().as_ref(),
            dapp.player_count.to_le_bytes().as_ref() // or similar
        ],
        bump
    )]
    pub player_pda: Account<'info, PlayerPda>,

    #[account(init,
        payer = validator,
        space = PlayerNamePda::LEN,
        seeds = [
            b"player_name",
            dapp.key().as_ref(),
            name.as_bytes()
        ],
        bump
    )]
    pub player_name_pda: Account<'info, PlayerNamePda>,

    #[account(
        mut, 
        constraint = fancy_mint.key() == dapp.mint_pubkey
    )]
    pub fancy_mint: InterfaceAccount<'info, Mint>,
    pub gateway_token: UncheckedAccount<'info>,
    /// If you want leftover for user_ata that’s fine,
    /// or add a field here for user_ata if needed
    /// leftover is optional.

    pub system_program: Program<'info, System>,
    // plus associated_token_program, token_program, etc. if needed
}

// --------------------------------------------------------------------
// The Program Module
// --------------------------------------------------------------------
#[program]
pub mod fancoin {
    use super::*;
    pub fn initialize_dapp_and_mint( //nogate
        ctx: Context<InitializeDappAndMint>,
        description: String,
        socials: String,
        commission_percent: u16,
        coin_issuance_rate: u64,
        validator_claim_rate: u64,
        curated_val: bool,
        initial_commission_tokens: u64,
        gatekeeper_network: Pubkey,
        player_limit: u32   // <--- new argument

    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
    
        // (A) Check commission_percent <= 100
        require!(
            commission_percent <= 100,
            ErrorCode::CommissionTooLarge
        );
    
        // (B) Basic info
        dapp.description = description;
        dapp.socials = socials;
        dapp.validator_count = 0;
        dapp.active_validator_count = 0;
        dapp.last_reset_hour = None;
        dapp.last_seed = None;
        dapp.last_punch_in_time = None;
        dapp.player_count = 0;
        dapp.player_limit = player_limit;

        require!(
            coin_issuance_rate <= 60_000_000,
            ErrorCode::IssuanceRateTooLarge
        );
        require!(
            validator_claim_rate <= 60_000_000,
            ErrorCode::ClaimRateTooLarge
        );
        // Also ensure commission <= 100, etc.
        require!(commission_percent <= 100, ErrorCode::CommissionTooLarge);
    
        // (C) Commission / gating
        dapp.commission_ata = ctx.accounts.commission_ata.key();  
        dapp.commission_percent = commission_percent;
        dapp.coin_issuance_rate = coin_issuance_rate;
        dapp.validator_claim_rate = validator_claim_rate;
        dapp.curated_val = curated_val;
        dapp.gatekeeper_network = gatekeeper_network;
        // (D) Store the minted pubkey
        dapp.mint_pubkey = ctx.accounts.mint_for_dapp.key();
    
        // (E) Set the new owner
        dapp.owner = ctx.accounts.user.key();
    
        // (F) Bump for mint_authority
        let bump = ctx.bumps.mint_authority;
        ctx.accounts.mint_authority.bump = bump;
    
        // (G) If you want to pre-mint tokens to commission_ata
        if initial_commission_tokens > 0 {

            let seeds = &[
                b"mint_authority".as_ref(),
                &[bump],
            ];
            let signer_seeds = &[&seeds[..]];  // a slice of slices
        

            let cpi_ctx = CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                anchor_spl::token_2022::MintTo {
                    mint: ctx.accounts.mint_for_dapp.to_account_info(),
                    to: ctx.accounts.commission_ata.to_account_info(),
                    authority: ctx.accounts.mint_authority.to_account_info(),
                },
                signer_seeds
            );
            anchor_spl::token_2022::mint_to(cpi_ctx, initial_commission_tokens)?;
        }
    
        msg!(
            "Initialized => commission_ata={}, pct={}, issuance={}, val_rate={}, curated={}, owner={}",
            dapp.commission_ata,
            dapp.commission_percent,
            dapp.coin_issuance_rate,
            dapp.validator_claim_rate,
            dapp.curated_val,
            dapp.owner
        );
    
        Ok(())
    }
    pub fn transfer_ownership(//nogate
        ctx: Context<TransferOwnership>,
        new_owner: Pubkey,
    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        // The has_one check ensures .owner matches the `owner` signer
        dapp.owner = new_owner;
    
        msg!(
            "Ownership transferred => new_owner={}",
            new_owner
        );
        Ok(())
    }
    pub fn register_player_pda_by_validator<'info>( //gate
        ctx: Context<'_, '_, 'info, 'info, RegisterPlayerPdaByValidator<'info>>,
        mint_pubkey: Pubkey,
        name: String,
        user_authority: Pubkey,
    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        let player_pda = &mut ctx.accounts.player_pda;
        let player_name_pda = &mut ctx.accounts.player_name_pda;
        let leftover = &ctx.remaining_accounts;
        require!(dapp.curated_val, ErrorCode::DappIsNotCurated);
        require!(leftover.len() >= 1, ErrorCode::InsufficientLeftoverAccounts);
        let wallet_pda_accinfo = &leftover[0];
        let mut wallet_pda_data = Account::<WalletPda>::try_from(wallet_pda_accinfo)
            .map_err(|_| ErrorCode::InvalidSeeds)?;
        require!(wallet_pda_data.is_registered, ErrorCode::Unauthorized);
        let user_ata_accinfo = &leftover[1];
        let user_ata_pubkey = *user_ata_accinfo.key;
        // (A) Fill PlayerPda
        player_pda.name = name.clone();
        player_pda.authority = user_authority;
        player_pda.last_name_change = None;
        player_pda.last_reward_change = None;
        player_pda.partial_validators = Vec::new();
        player_pda.last_minted = None;
        player_pda.reward_address = user_ata_pubkey;
        player_pda.pending_game_time_ms = Some(0);
        player_pda.pending_claim_ts = Some(0);
        player_pda.pending_paid = false;
        player_pda.last_claim_ts = Some(0);
    
        // (B) Fill PlayerNamePda
        player_name_pda.name = name.clone();
        player_name_pda.player_pda = player_pda.key();
        player_name_pda.active = true;
    
        // (C) Increment dapp.player_count
        dapp.player_count += 1;
    
        msg!(
            "Curated registration => name='{}', user_authority={}, new player_pda={}",
            name,
            user_authority,
            player_pda.key()
        );
        Ok(())
    }
    
    pub fn lock_field(ctx: Context<LockField>, field_name: String) -> Result<()> { //nogate
        let dapp = &mut ctx.accounts.dapp;
    
        match field_name.as_str() {
            "lock_claim" => {
                dapp.claim_rate_lock = true;
                msg!("Locked validator_claim_rate field.");
            },
            "lock_coin_rate" => {
                dapp.coin_issuance_rate_lock = true;
                msg!("Locked coin_issuance_rate field.");
            },
            "lock_commission_pct" => {
                dapp.commission_percent_lock = true;
                msg!("Locked commission_percent field.");
            },
            _ => {
                msg!("Invalid field name => {}", field_name);
                return err!(ErrorCode::InvalidLockString);
            },
        }
    
        Ok(())
    }
    pub fn update_commission_info( //nogate
        ctx: Context<UpdateCommissionInfo>,
        new_commission_ata: Pubkey,
        new_commission_percent: u16,
        new_coin_issuance_rate: u64,
        new_validator_claim_rate: u64,
    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
    
        // Always allow updating commission_ata, unless you also implement a lock for it:
        dapp.commission_ata = new_commission_ata;
    
        if !dapp.commission_percent_lock {
            require!(new_commission_percent <= 100, ErrorCode::CommissionTooLarge);
            dapp.commission_percent = new_commission_percent;
        } else {
            msg!("Commission percent is locked; skipping update.");
        }
    
        if !dapp.coin_issuance_rate_lock {
            require!(new_coin_issuance_rate <= 60_000_000, ErrorCode::IssuanceRateTooLarge);
            dapp.coin_issuance_rate = new_coin_issuance_rate;
        } else {
            msg!("Coin issuance rate is locked; skipping update.");
        }
    
        if !dapp.claim_rate_lock {
            require!(new_validator_claim_rate <= 60_000_000, ErrorCode::ClaimRateTooLarge);
            dapp.validator_claim_rate = new_validator_claim_rate;
        } else {
            msg!("Validator claim rate is locked; skipping update.");
        }
    
        msg!(
            "Updated => commission_ata={}, pct={}, coin_rate={}, val_claim_rate={}",
            dapp.commission_ata,
            dapp.commission_percent,
            dapp.coin_issuance_rate,
            dapp.validator_claim_rate
        );
    
        Ok(())
    }
    
    pub fn validate_player_pubg_time_slim<'info>( //nogate
        ctx: Context<'_, '_, 'info, 'info, ValidatePlayerPubgTimeSlim<'info>>,
        mint_pubkey: Pubkey,
        name: String,
        new_time_seconds: u64,
    ) -> Result<()> {
        // 1) Basic references
        let dapp = &ctx.accounts.dapp;
        let validator = &ctx.accounts.validator;
        let leftover = &ctx.remaining_accounts;
        require!(
            leftover.len() >= 6,
            ErrorCode::InsufficientLeftoverAccounts
        );
    
        // 2) We'll define the order we expect leftover accounts:
        //    0: player_name_pda
        //    1: player_pda
        //    2: fancy_mint
        //    3: mint_authority
        //    4: user_ata
        //    5: validator_pda
        //    6: (Optional) commission_ata
        let player_name_pda_accinfo    = &leftover[0];
        let player_pda_accinfo         = &leftover[1];
        let fancy_mint_accinfo         = &leftover[2];
        let mint_authority_accinfo     = &leftover[3];
        let user_ata_accinfo           = &leftover[4];
        let validator_pda_accinfo      = &leftover[5];
        // leftover[6] => commission_ata_accinfo (optional)
    
        // ------------------------------------------------------
        // (A) Parse + Verify PlayerNamePda
        // ------------------------------------------------------
        let (expected_name_pda, _bump) = Pubkey::find_program_address(
            &[
                b"player_name",
                dapp.key().as_ref(),
                name.as_bytes(),
            ],
            ctx.program_id,
        );
        require!(
            player_name_pda_accinfo.key() == expected_name_pda,
            ErrorCode::InvalidSeeds
        );
        let player_name_pda = Account::<PlayerNamePda>::try_from(player_name_pda_accinfo)
            .map_err(|_| ErrorCode::InvalidSeeds)?;
    
        // ------------------------------------------------------
        // (B) Parse + Verify PlayerPda
        // ------------------------------------------------------
        require!(
            player_pda_accinfo.key() == player_name_pda.player_pda,
            ErrorCode::InvalidSeeds
        );
        let mut player_pda = Account::<PlayerPda>::try_from(player_pda_accinfo)
            .map_err(|_| ErrorCode::InvalidSeeds)?;
    
        // ------------------------------------------------------
        // (C) Parse + Verify fancy_mint
        // ------------------------------------------------------
        require!(
            fancy_mint_accinfo.key() == dapp.mint_pubkey,
            ErrorCode::InvalidSeeds
        );
        let fancy_mint = InterfaceAccount::<Mint>::try_from(fancy_mint_accinfo)
            .map_err(|_| ErrorCode::InvalidSeeds)?;
    
        // ------------------------------------------------------
        // (D) Parse + Verify mint_authority
        // ------------------------------------------------------
        let (expected_ma, bump_ma) = Pubkey::find_program_address(
            &[b"mint_authority"],
            ctx.program_id,
        );
        require!(
            mint_authority_accinfo.key() == expected_ma,
            ErrorCode::InvalidSeeds
        );
        let mint_authority = Account::<MintAuthority>::try_from(mint_authority_accinfo)
            .map_err(|_| ErrorCode::InvalidSeeds)?;
    
        // ------------------------------------------------------
        // (E) Parse user_ata => confirm matches player_pda.reward_address
        // ------------------------------------------------------
        let user_ata = InterfaceAccount::<TokenAccount>::try_from(user_ata_accinfo)
            .map_err(|_| ErrorCode::InvalidAtaAccount)?;
        require!(
            user_ata_accinfo.key() == player_pda.reward_address,
            ErrorCode::InvalidAtaAccount
        );
    
        // ------------------------------------------------------
        // (F) Parse + Verify validator_pda
        // ------------------------------------------------------
        let (expected_val_pda, _val_bump) = Pubkey::find_program_address(
            &[
                b"validator",
                dapp.mint_pubkey.as_ref(),
                validator.key().as_ref(),
            ],
            ctx.program_id,
        );
        require!(
            validator_pda_accinfo.key() == expected_val_pda,
            ErrorCode::ValidatorNotRegistered
        );
        let mut val_pda = Account::<ValidatorPda>::try_from(validator_pda_accinfo)
            .map_err(|_| ErrorCode::ValidatorNotRegistered)?;
        require!(
            val_pda.address == validator.key(),
            ErrorCode::ValidatorNotRegistered
        );
    
        // ------------------------------------------------------
        // Normal logic: compare new_time_seconds, clamp, update PlayerPda, etc.
        // ------------------------------------------------------
        let old_time = player_pda.pending_game_time_ms.unwrap_or(0);
        let difference = new_time_seconds.saturating_sub(old_time as u64);
        let max_seconds = 8 * 3600;
        let final_diff = difference.min(max_seconds);
    
        // Update player_pda
        player_pda.pending_game_time_ms = Some(new_time_seconds as i64);
    
        // Convert final_diff to minted tokens:
        let diff_minutes = final_diff / 60;
        let minted_amount = diff_minutes.saturating_mul(dapp.coin_issuance_rate);
    
        // If nothing to mint => skip
        if minted_amount == 0 {
            player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
            return Ok(());
        }
    
        // ------------------------------------------------------
        // Mint to user_ata
        // ------------------------------------------------------
        let seeds_ma: &[&[u8]] = &[b"mint_authority", &[bump_ma]];
        let signer_seeds = &[&seeds_ma[..]];
    
        let cpi_ctx_user = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: fancy_mint.to_account_info(),
                to: user_ata_accinfo.to_account_info(),
                authority: mint_authority_accinfo.to_account_info(),
            },
            signer_seeds,
        );
        anchor_spl::token_2022::mint_to(cpi_ctx_user, minted_amount)?;
    
        // ------------------------------------------------------
        // (G) Commission logic
        // ------------------------------------------------------
        if dapp.commission_percent > 0 {
            let commission_amount = (minted_amount as u128)
                .checked_mul(dapp.commission_percent as u128)
                .unwrap_or(0)
                / 100;
            let commission_amount = commission_amount as u64;
    
            if commission_amount > 0 {
                // Check if leftover[6] is present
                if leftover.len() > 6 {
                    let commission_ata_accinfo = &leftover[6];
                    let commission_ata = InterfaceAccount::<TokenAccount>::try_from(commission_ata_accinfo)
                        .map_err(|_| ErrorCode::InvalidAtaAccount)?;
    
                    // Optionally confirm the ownership, e.g. `commission_ata.owner == validator.key()`
                    // Or just let it be any valid ATA
    
                    let cpi_ctx_commission = CpiContext::new_with_signer(
                        ctx.accounts.token_program.to_account_info(),
                        MintTo {
                            mint: fancy_mint.to_account_info(),
                            to: commission_ata_accinfo.to_account_info(),
                            authority: mint_authority_accinfo.to_account_info(),
                        },
                        signer_seeds,
                    );
                    anchor_spl::token_2022::mint_to(cpi_ctx_commission, commission_amount)?;
                } else {
                    msg!(
                        "Commission percent={} > 0, but leftover[6] not provided => skipping commission mint",
                        dapp.commission_percent
                    );
                }
            }
        }
    
        // ------------------------------------------------------
        // (H) Update val_pda (optional)
        // ------------------------------------------------------
        val_pda.last_minted = Some(Clock::get()?.unix_timestamp);
    
        // ------------------------------------------------------
        // Re-serialize both player_pda and val_pda
        // ------------------------------------------------------
        player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
        val_pda.try_serialize(&mut &mut validator_pda_accinfo.try_borrow_mut_data()?[..])?;
    
        msg!(
            "validate_player_pubg_time_slim => old_time={}, new_time={}, diff={}, minted={}, commission={}",
            old_time,
            new_time_seconds,
            final_diff,
            minted_amount,
            dapp.commission_percent
        );
        Ok(())
    }
    

    pub fn register_validator_curated( //nogate
        ctx: Context<RegisterValidatorCurated>,
        mint_pubkey: Pubkey,
        validator_to_add: Pubkey,
    ) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        require!(dapp.curated_val, ErrorCode::DappIsNotCurated);
    
        // Fill in the new validator data
        let val_pda = &mut ctx.accounts.validator_pda;
        val_pda.address = validator_to_add;
        val_pda.last_activity = 0;
        val_pda.last_minted = None;
        val_pda.last_claimed = None;
    
        // Increment validator_count
        dapp.validator_count += 1;
    
        msg!(
            "Curated validator registration => new_validator={}, ATA={}, dapp={}",
            validator_to_add,
            ctx.accounts.validator_ata.key(),
            dapp.key()
        );
        Ok(())
    }
    
    pub fn request_claim( //gate
        ctx: Context<RequestClaim>,
        _mint_pubkey: Pubkey,
        name: String,
    ) -> Result<()> {
        let player = &mut ctx.accounts.player_pda;
        let user = &ctx.accounts.user;
    
        // (A) Authority check
        require!(
            player.authority == user.key(),
            ErrorCode::Unauthorized
        );
        let gateway_token_info = ctx.accounts.gateway_token.to_account_info();
        Gateway::verify_gateway_token_account_info(
            &gateway_token_info,
            &ctx.accounts.user.key(),
            &ctx.accounts.dapp.gatekeeper_network,
            None,
        )
        .map_err(|_e| {
            msg!("Gateway token account verification failed");
            ProgramError::InvalidArgument
        })?;
        msg!("Gateway token verification passed");
        // (B) If there's a pending claim older than ~24h, mark it as "paid" so user can request again
        let now = Clock::get()?.unix_timestamp;
        const SIX_HOURS_MINUS_ONE_MIN: i64 = 5*3600 + 59*60;
    
        if let Some(ts) = player.pending_claim_ts {
            let diff = now.saturating_sub(ts);
            if !player.pending_paid && diff > SIX_HOURS_MINUS_ONE_MIN {
                // This pending claim is ancient => treat it as paid so the user can request again
                player.pending_paid = true;
                player.pending_claim_ts = Some(now);
                msg!("Old pending claim auto-set to paid => diff={}s, Current time={}", diff, now);
            }
        }
    
   
        msg!("request_claim => name={}, player_pda={}", name, player.key());
        Ok(())
    }
    
    
    pub fn punch_in(ctx: Context<PunchIn>, mint_pubkey: Pubkey) -> Result<()> { //gate
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let dapp = &ctx.accounts.dapp;
        // let gateway_token_info = ctx.accounts.gateway_token.to_account_info();

        // // Gateway::verify_gateway_token_account_info(
        // //     &gateway_token_info,
        // //     &ctx.accounts.validator.key(),
        // //     &ctx.accounts.dapp.gatekeeper_network,
        // //     None,
        // // )
        // // .map_err(|_e| {
        // //     msg!("Gateway token account verification failed");
        // //     ProgramError::InvalidArgument
        // // })?;
        // // msg!("Gateway token verification passed");

        let dapp = &mut ctx.accounts.dapp;

        // Basic checks
        //require!(dapp.dapp_number == dapp_number, ErrorCode::DappNumberMismatch);
    
        // ----------------------------------------------------------
        // (1) Identify hour + minute, do new-hour reset, enforce first-7-min rule
        // ----------------------------------------------------------
        let current_hour = (current_time / 3600) as u32;
        let current_minute = ((current_time % 3600) / 60) as u32;
    
        // If a new hour started (compare to last_reset_hour), reset active_validator_count to 0
        // and set dapp.last_reset_hour = Some(current_hour).
        if let Some(last_reset_hour) = dapp.last_reset_hour {
            if current_hour > last_reset_hour {
                // We have rolled over into a new hour
                dapp.active_validator_count = 0;
                dapp.last_reset_hour = Some(current_hour);
                msg!("New hour => reset active_validator_count to 0 for hour {}", current_hour);
            }
        } else {
            // If last_reset_hour was never set, initialize it now
            dapp.last_reset_hour = Some(current_hour);
            msg!("Initializing last_reset_hour => {}", current_hour);
        }
    
        // ----------------------------------------------------------
        // (2) Mark the validator as active if they haven't punched in this hour
        // ----------------------------------------------------------
        let validator_key = ctx.accounts.validator.key();
        let val_pda = &mut ctx.accounts.validator_pda;
        let last_activity = val_pda.last_activity;
    
        let validator_last_hour = if last_activity > 0 {
            (last_activity / 3600) as u32
        } else {
            0
        };
        if validator_last_hour < current_hour {
            // If the validator hasn't punched in this hour yet
            if dapp.active_validator_count < dapp.validator_count {
                dapp.active_validator_count += 1;
                msg!(
                    "Validator {} is active this hour {} => total active={}",
                    validator_key,
                    current_hour,
                    dapp.active_validator_count
                );
            }
        }
    
        // Update validator's last_activity
        val_pda.last_activity = current_time;
    
        // ----------------------------------------------------------
        // (3) Original seed + last_punch_in_time logic
        // ----------------------------------------------------------
        let mut hasher = Keccak256::new();
        hasher.update(validator_key.to_bytes());
        hasher.update(clock.slot.to_le_bytes());
        let hash_res = hasher.finalize();
        let seed = u64::from_le_bytes(
            hash_res[0..8].try_into().map_err(|_| ErrorCode::HashConversionError)?
        );
        dapp.last_seed = Some(seed);
        dapp.last_punch_in_time = Some(current_time);
    
        msg!(
            "Punch in => seed={}, time={}, hour={}, minute={}",
            seed,
            current_time,
            current_hour,
            current_minute
        );
        Ok(())
    }
    pub fn create_user_ata_if_needed( //gate
        ctx: Context<CreateUserAtaIfNeeded>,
        mint_pubkey: Pubkey,
    ) -> Result<()> {
        // 1) Mark the wallet_pda as registered (if it wasn’t already).
        let gateway_token_info = ctx.accounts.gateway_token.to_account_info();
        Gateway::verify_gateway_token_account_info(
            &gateway_token_info,
            &ctx.accounts.user.key(),
            &ctx.accounts.dapp.gatekeeper_network,
            None,
        )
        .map_err(|_e| {
            msg!("Gateway token account verification failed");
            ProgramError::InvalidArgument
        })?;
        msg!("Gateway token verification passed");
        
        let wallet_pda = &mut ctx.accounts.wallet_pda;
        if !wallet_pda.is_registered {
            wallet_pda.wallet = ctx.accounts.user.key();
            wallet_pda.is_registered = true;
            msg!("Initialized wallet_pda => {}", wallet_pda.key());
        } else {
            msg!("wallet_pda already registered => skipping");
        }
    
        // 2) The user_ata is also auto-created if needed (via init_if_needed).
        // We don't have to do anything more here.
    
        Ok(())
    }
    pub fn update_player_name_cooldown( //gate
        ctx: Context<UpdatePlayerNameCooldown>,
        mint_pubkey: Pubkey,  // if you need it for seeds or leftover checks
        new_name: String
    ) -> Result<()> {
        let pda = &mut ctx.accounts.player_pda;
        let old_name_pda = &mut ctx.accounts.old_name_pda;
        let new_name_pda = &mut ctx.accounts.new_name_pda;
    
        let now = Clock::get()?.unix_timestamp;
        let one_day = 24 * 3600;
        let gateway_token_info = ctx.accounts.gateway_token.to_account_info();
        Gateway::verify_gateway_token_account_info(
            &gateway_token_info,
            &ctx.accounts.user.key(),
            &ctx.accounts.dapp.gatekeeper_network,
            None,
        )
        .map_err(|_e| {
            msg!("Gateway token account verification failed");
            ProgramError::InvalidArgument
        })?;
        msg!("Gateway token verification passed");
        // 1) Ownership + Cooldown
        require!(pda.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);
        if let Some(last_change) = pda.last_name_change {
            require!(now - last_change >= one_day, ErrorCode::NameChangeCooldown);
        }
    
        // 2) Mark the old name as inactive
        //    (As long as old_name_pda matches pda.name)
        require!(old_name_pda.active, ErrorCode::NameChangeCooldown); // or some error if already inactive?
        old_name_pda.active = false;
    
        // 3) Now set the new name => also set new_name_pda
        //    Usually you’d check “new_name_pda.active == false” 
        //    but since we used `init`, this account is brand new => default active=false
        //    We set active=true to claim it:
        new_name_pda.name = new_name.clone();
        new_name_pda.player_pda = pda.key();
        new_name_pda.active = true;
    
        // 4) Update PlayerPda
        pda.name = new_name;
        pda.last_name_change = Some(now);
    
        msg!("Player name changed => now={}", pda.name);
        Ok(())
    }

    pub fn update_player_reward_cooldown( //gate
        ctx: Context<UpdatePlayerRewardCooldown>,
        new_reward: Pubkey,
    ) -> Result<()> {
        let pda = &mut ctx.accounts.player_pda;
        let now = Clock::get()?.unix_timestamp;
        let one_day = 24 * 3600;

        require!(pda.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);
    
        if let Some(last_change) = pda.last_reward_change {
            require!(now - last_change >= one_day, ErrorCode::RewardChangeCooldown);
        }
    
        pda.reward_address = new_reward;
        pda.last_reward_change = Some(now);
    
        Ok(())
    }
    /// Register a player with a unique name by initializing PlayerPda + PlayerNamePda
    pub fn register_player_pda<'info>( //gate if fits
        ctx: Context<'_, '_, 'info, 'info, RegisterPlayerPda<'info>>,
        mint_pubkey: Pubkey,
        name: String,
    ) -> Result<()> {

        let dapp = &ctx.accounts.dapp;
        let player = &mut ctx.accounts.player_pda;
        let name_pda = &mut ctx.accounts.player_name_pda;
        let leftover_accs = &ctx.remaining_accounts;
        if dapp.player_limit != 0 {
            require!(
                dapp.player_count < dapp.player_limit,
                ErrorCode::PlayerLimitReached
            );
        }
        require!(
            !leftover_accs.is_empty(),
            ErrorCode::InsufficientLeftoverAccounts
        );
        let gateway_token_info = ctx.accounts.gateway_token.to_account_info();
        Gateway::verify_gateway_token_account_info(
            &gateway_token_info,
            &ctx.accounts.user.key(),
            &ctx.accounts.dapp.gatekeeper_network,
            None,
        )
        .map_err(|_e| {
            msg!("Gateway token account verification failed");
            ProgramError::InvalidArgument
        })?;
        msg!("Gateway token verification passed");

        let dapp = &mut ctx.accounts.dapp;

        let wallet_pda_accinfo = &leftover_accs[0];
        let wallet_pda_data = Account::<WalletPda>::try_from(wallet_pda_accinfo)
            .map_err(|_| ErrorCode::InvalidSeeds)?;
        // Check if it's actually registered:
        require!(wallet_pda_data.is_registered, ErrorCode::Unauthorized);
    
        // leftover[1] => user_ata
        let user_ata_accinfo = &leftover_accs[1];

        let user_ata_result =
        InterfaceAccount::<TokenAccount>::try_from(user_ata_accinfo);

        require!(user_ata_result.is_ok(), ErrorCode::InvalidAtaAccount);
        let user_ata = user_ata_result.unwrap();

        // (A) Enforce max name length
        require!(name.len() <= PlayerNamePda::MAX_NAME_LEN, ErrorCode::InvalidNameLength);

        // (B) Fill in PlayerPda
        player.name = name.clone();
        player.authority = ctx.accounts.user.key();
        player.last_name_change = None;
        player.last_reward_change = None;
        player.partial_validators = Vec::new();
        player.last_minted = None;
        player.reward_address = user_ata.key();
        player.pending_game_time_ms = Some(0);
        player.pending_claim_ts = Some(0);
        player.pending_paid = false;
        player.last_claim_ts = Some(0);

        // (C) Initialize PlayerNamePda data
        name_pda.name = name;
        name_pda.player_pda = player.key();

        // (D) Increment global_player_count
        dapp.player_count += 1;

        msg!(
            "Registered player => name='{}', authority={}, ATA={}, name_pda={}",
            player.name,
            player.authority,
            player.reward_address,
            name_pda.key()
        );
        Ok(())
    }

    // pub fn register_validator_pda<'info>( //gate
    //     ctx: Context<'_, '_, 'info, 'info, RegisterValidatorPda<'info>>,
    //     mint_pubkey: Pubkey
    // ) -> Result<()> {
    //     let dapp = &ctx.accounts.dapp;
    //     //require!(dapp.dapp_number == dapp_number, ErrorCode::DappNumberMismatch);
    //     require!(!dapp.curated_val, ErrorCode::DappIsCurated);
    //     let leftover = &ctx.remaining_accounts;
    //     require!(leftover.len() >= 1, ErrorCode::InsufficientLeftoverAccounts);
    //     let wallet_pda_accinfo = &leftover[0];
    //     let wallet_pda_data = Account::<WalletPda>::try_from(wallet_pda_accinfo)
    //         .map_err(|_| ErrorCode::InvalidSeeds)?;
    //     require!(wallet_pda_data.is_registered, ErrorCode::Unauthorized);
    //     let gateway_token_info = ctx.accounts.gateway_token.to_account_info();
    //     Gateway::verify_gateway_token_account_info(
    //         &gateway_token_info,
    //         &ctx.accounts.user.key(),
    //         &ctx.accounts.dapp.gatekeeper_network,
    //         None,
    //     )
    //     .map_err(|_e| {
    //         msg!("Gateway token account verification failed");
    //         ProgramError::InvalidArgument
    //     })?;
    //     msg!("Gateway token verification passed");
    //     let dapp = &mut ctx.accounts.dapp;

    //     let val_pda = &mut ctx.accounts.validator_pda;
    //     val_pda.address = ctx.accounts.user.key();
    //     val_pda.last_activity = Clock::get()?.unix_timestamp;
    //     val_pda.last_minted = None; // new

    //     dapp.validator_count += 1;
    //     msg!(
    //         "Registered validator => dapp={}, validator={}, ATA={}",
    //         mint_pubkey,
    //         val_pda.address,
    //         ctx.accounts.validator_ata.key()
    //     );
    //     Ok(())
    // }


    /// The main multi-player mint function
    /// (We do *NOT* mint to validators here. Instead, we simply set val_pda.last_minted = now.)
    pub fn submit_minting_list<'info>( //gate unless curated, figure out
        ctx: Context<'_, '_, 'info, 'info, SubmitMintingList<'info>>,
        mint_pubkey: Pubkey,
        player_ids: Vec<u32>,
    ) -> Result<()> {
        let dapp = &ctx.accounts.dapp;
    
        // 1) Basic checks on validator PDA, etc. unchanged
        let (expected_pda, _bump) = Pubkey::find_program_address(
            &[
                b"validator",
                mint_pubkey.as_ref(),
                ctx.accounts.validator.key().as_ref(),
            ],
            ctx.program_id,
        );
        require!(
            ctx.accounts.validator_pda.key() == expected_pda,
            ErrorCode::ValidatorNotRegistered
        );
        if !dapp.curated_val {
            let gateway_token_info = ctx.accounts.gateway_token.to_account_info();
            Gateway::verify_gateway_token_account_info(
                &gateway_token_info,
                &ctx.accounts.validator.key(),
                &ctx.accounts.dapp.gatekeeper_network,
                None,
            )
            .map_err(|_e| {
                msg!("Gateway token account verification failed");
                ProgramError::InvalidArgument
            })?;
            msg!("Gateway token verification passed");
        } else {
            msg!("Dapp is curated => skipping gateway token check");
        }
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let current_hour = (current_time / 3600) as u32;
        let current_minute = ((current_time % 3600) / 60) as u32;
    
        let Some(last_punch) = dapp.last_punch_in_time else {
            msg!("No one has punched in => cannot mint");
            return Ok(());
        };
        let punched_hour = (last_punch / 3600) as u32;
        if punched_hour != current_hour {
            msg!("No one has punched in this hour => cannot mint");
            return Ok(());
        }
    
        let val_pda = &mut ctx.accounts.validator_pda;
        let validator_hour = (val_pda.last_activity / 3600) as u32;
        if validator_hour != current_hour {
            msg!("Validator hasn't used punch_in this hour => can't mint");
            return Ok(());
        }
    
        // --------------------------------------------------------
        // Example: If you still want to block first 7 minutes, do:
        if current_minute < 7 {
            msg!("Minting is blocked during the first 7 minutes.");
            return Ok(());
        }
        // --------------------------------------------------------
    
        msg!("submit_minting_list => player_ids={:?}", player_ids);
        let total_vals = dapp.validator_count as usize;
        let active_vals = dapp.active_validator_count as usize;
        let total_groups = (total_vals + 3) / 4;
        let failover_tolerance = calculate_failover_tolerance(total_vals) as u64;
    
        // --------------------------------------------------------
        // 2) Handle leftover accounts
        //    We'll read the very first leftover as the commission ATA
        //    Then pairs of leftover for each player: [PlayerPda, PlayerATA]
        // --------------------------------------------------------
        let mut leftover_iter = ctx.remaining_accounts.iter();
    
        // 2a) Commission ATA leftover
        let Some(commission_ata_accinfo) = leftover_iter.next() else {
            msg!("No leftover for commission_ata => skipping commission logic");
            // If you want to *require* it, you can do `return err!()` instead:
            return err!(ErrorCode::MissingCommissionAta);
            // For now, let's just continue with no commission minted.
        };
    
        // 2b) Confirm it matches dapp.commission_ata 
        //     (assuming your Dapp struct has 'commission_ata: Pubkey')
        if commission_ata_accinfo.key() != dapp.commission_ata {
            msg!("Commission ATA mismatch => leftover={} dapp={}",
                commission_ata_accinfo.key(), dapp.commission_ata
            );
            // You can error out here if mismatch should fail the entire call
            // or just skip commission. We'll error out for demonstration:
            return err!(ErrorCode::InvalidCommissionAta);
        }
    
        // 2c) We *try* reading it as a TokenAccount to ensure it is valid

        let _is_ata_ok = InterfaceAccount::<TokenAccount>::try_from(&commission_ata_accinfo).is_ok();
        if !_is_ata_ok {
            msg!("Leftover commission_ata is not a valid TokenAccount => skipping commission");
            return err!(ErrorCode::InvalidCommissionAta);
        }
        // leftover pairs for each player
        let mut minted_count = 0_usize;
    
        for pid in player_ids {
            let Some(seed) = dapp.last_seed else {
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
            //-- NEW concurrency check (Part 1): store the original last_minted
            let original_last_minted = player_pda.last_minted.unwrap_or(0);

            // (A) Add this validator if not in partial_validators
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
    
            // (B) If partial_validators < required => skip
            if (active_vals > 1 && player_pda.partial_validators.len() < 2)
                || (active_vals == 1 && player_pda.partial_validators.len() < 1)
            {
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
    
            // (D) Time gating => 7..34 minutes (example)
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
            //     We now use dapp.coin_issuance_rate instead of a hard-coded value
            let minted_amount = diff_minutes.saturating_mul(dapp.coin_issuance_rate);
    
            let is_ata_ok = InterfaceAccount::<TokenAccount>::try_from(&player_ata_accinfo).is_ok();
            if !is_ata_ok {
                msg!("Leftover is NOT a valid TokenAccount => skip pid={}", pid);
                player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
            if player_pda.last_minted.unwrap_or(0) != original_last_minted {
                msg!(
                    "Concurrent update => skip mint for player={}, pid={}",
                    player_pda.name,
                    pid
                );
                // Optionally keep partial_validators or clear it. 
                // Let's just preserve them and skip.
                player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
                continue;
            }
            // Prepare MintTo seeds
            let bump = ctx.accounts.mint_authority.bump;
            let seeds_auth: &[&[u8]] = &[b"mint_authority".as_ref(), &[bump]];
            let signer_seeds = &[&seeds_auth[..]];
    
            // CPI to mint to the Player
            let cpi_ctx_player = CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.fancy_mint.to_account_info(),
                    to: player_ata_accinfo.to_account_info(),
                    authority: ctx.accounts.mint_authority.to_account_info(),
                },
                signer_seeds,
            );
            token_2022::mint_to(cpi_ctx_player, minted_amount)?;
    
            // (E2) Mint Commission if any
            if dapp.commission_percent > 0 {
                let commission_amount = (minted_amount as u128)
                    .checked_mul(dapp.commission_percent as u128)
                    .unwrap_or(0)
                    / 100;
                // Cast back to u64 safely
                let commission_amount = commission_amount as u64;
                if commission_amount > 0 {
                    let cpi_ctx_commission = CpiContext::new_with_signer(
                        ctx.accounts.token_program.to_account_info(),
                        MintTo {
                            mint: ctx.accounts.fancy_mint.to_account_info(),
                            to: commission_ata_accinfo.to_account_info(),
                            authority: ctx.accounts.mint_authority.to_account_info(),
                        },
                        signer_seeds,
                    );
                    token_2022::mint_to(cpi_ctx_commission, commission_amount)?;
                    msg!("Commission minted={} => pid={}", commission_amount, pid);
                }
            }
    
            // (F) Mark *this* validator (the signer) as minted now, clear partial_validators
            ctx.accounts.validator_pda.last_minted = Some(current_time);
            player_pda.partial_validators.clear();
            player_pda.last_minted = Some(current_time);
            player_pda.try_serialize(&mut &mut player_pda_accinfo.try_borrow_mut_data()?[..])?;
    
            msg!("Minted {} => pid={}", minted_amount, pid);
            minted_count += 1;
        }
    
        msg!("submit_minting_list => minted for {} players", minted_count);
        Ok(())
    }
    

    pub fn claim_validator_reward<'info>( //gate unless curated
        ctx: Context<'_, '_, 'info, 'info, ClaimValidatorReward<'info>>,
        mint_pubkey: Pubkey
    ) -> Result<()> {
        let val_pda = &mut ctx.accounts.validator_pda;
        require!(
            val_pda.address == ctx.accounts.validator.key(),
            ErrorCode::ValidatorNotRegistered
        );
    
        let leftover_accs = &ctx.remaining_accounts;
        require!(
            !leftover_accs.is_empty(),
            ErrorCode::InsufficientLeftoverAccounts
        );
        let clock = Clock::get()?;
        let gateway_token_info = ctx.accounts.gateway_token.to_account_info();
        Gateway::verify_gateway_token_account_info(
            &gateway_token_info,
            &ctx.accounts.validator.key(),
            &ctx.accounts.dapp.gatekeeper_network,
            None,
        )
        .map_err(|_e| {
            msg!("Gateway token account verification failed");
            ProgramError::InvalidArgument
        })?;
        msg!("Gateway token verification passed");
        // (A) Attempt to parse leftover[0] as the validator's ATA
        let val_ata_accinfo = &leftover_accs[0];
        let val_ata_result = InterfaceAccount::<TokenAccount>::try_from(val_ata_accinfo);
        require!(val_ata_result.is_ok(), ErrorCode::InvalidAtaAccount);
        let val_ata = val_ata_result.unwrap();
    
        // (B) Ensure last_minted is within 60 minutes from now
        let current_time = clock.unix_timestamp;
        let last_minted = val_pda.last_minted.unwrap_or(0);
        let minted_diff = current_time.saturating_sub(last_minted);
        // minted_diff in seconds, must be <= 3600 (60 min)
        if minted_diff > 60 * 60 {
            msg!(
                "No reward => last_minted too long ago ({} minutes). Skipping.",
                minted_diff / 60
            );
            return Ok(());
        }
    
        // (C) Calculate how many minutes to reward based on last_claimed
        let last_claimed = val_pda.last_claimed.unwrap_or(0);
        let diff_seconds = current_time.saturating_sub(last_claimed);
        let diff_minutes = diff_seconds as u64 / 60;
        // Cap it at 60 => 1 hour max
        let minutes_capped = diff_minutes.min(60);
    
        if minutes_capped == 0 {
            msg!("No reward => last_claimed was too recent => skipping");
            return Ok(());
        }
    
        let tokens_per_minute_lamports: u64 = 28_570;

        // minutes_capped = how many minutes since last_claimed, capped at 60
        let minted_amount = tokens_per_minute_lamports.saturating_mul(minutes_capped);
        if minted_amount == 0 {
            msg!("No reward => skipping");
            return Ok(());
        }
    
        // (E) Mint to validator’s ATA
        let bump = ctx.accounts.mint_authority.bump;
        let seeds_auth: &[&[u8]] = &[b"mint_authority".as_ref(), &[bump]];
        let signer_seeds = &[&seeds_auth[..]];
    
        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: ctx.accounts.fancy_mint.to_account_info(),
                to: val_ata.to_account_info(),
                authority: ctx.accounts.mint_authority.to_account_info(),
            },
            signer_seeds,
        );
    
        // (F) Update `last_claimed` but *not* `last_minted`
        val_pda.last_claimed = Some(current_time);
        token_2022::mint_to(cpi_ctx, minted_amount)?;

        msg!(
            "Claimed {} tokens => validator={} after {} minutes (capped at 60). minted_diff={} min",
            minted_amount,
            val_pda.address,
            diff_minutes,
            minted_diff / 60
        );
    
        Ok(())
    }
}

// --------------------------------------------------------------------
//  Additional Accounts for claim_validator_reward
// --------------------------------------------------------------------
#[derive(Accounts)]
#[instruction(mint_pubkey: Pubkey)]
pub struct ClaimValidatorReward<'info> {
    #[account(
        mut,
        seeds = [b"dapp", mint_pubkey.as_ref()],
        bump
    )]
    pub dapp: Account<'info, Dapp>,

    #[account(
        mut,
        seeds = [b"validator", mint_pubkey.as_ref(), validator.key().as_ref()],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,
    #[account(mut)]
    pub validator: Signer<'info>,
    #[account(mut, constraint = fancy_mint.key() == dapp.mint_pubkey)]
    pub fancy_mint: InterfaceAccount<'info, Mint>, 
    pub gateway_token: UncheckedAccount<'info>,
    #[account(
        seeds = [b"mint_authority"],
        bump = mint_authority.bump
    )]
    pub mint_authority: Account<'info, MintAuthority>,

    #[account(address = TOKEN_2022_PROGRAM_ID)]  // Changed from `token::ID` to `spl_token_2022::ID`
    pub token_program: Program<'info, Token2022>,

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
    #[msg("Dapp number mismatch.")]
    DappNumberMismatch,
    #[msg("Dapp is blacklisted.")]
    DappIsBlacklisted,
    #[msg("Dapp not whitelisted.")]
    DappNotWhitelisted,
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
    #[msg("Insufficient leftover accounts.")]
    InsufficientLeftoverAccounts,
    #[msg("Invalid associated token account.")]
    InvalidAtaAccount,
    #[msg("Reward address was changed recently (wait a day.)")]
    RewardChangeCooldown,
    #[msg("Name was changed recently (wait a day.)")]
    NameChangeCooldown,
    #[msg("Commission ATA missing.")]
    MissingCommissionAta,
    #[msg("Commission ATA invalid (not a valid ATA acct?)")]
    InvalidCommissionAta,
    #[msg("Commission percent cannot exceed 100%")]
    CommissionTooLarge,
    #[msg("Dapp is curated, so open registration is disallowed.")]
    DappIsCurated,
    #[msg("Dapp is not curated, so this instruction is disallowed.")]
    DappIsNotCurated,
    #[msg("Invalid field name for lock/unlock.")]
    InvalidLockString,
    #[msg("Coin issuance rate cannot exceed 60_000_000.")]
    IssuanceRateTooLarge,
    #[msg("Validator claim rate cannot exceed 60_000_000.")]
    ClaimRateTooLarge,
    #[msg("No pending claim found.")]
    NoPendingClaim,
    #[msg("Claim is already paid.")]
    ClaimAlreadyPaid,
    #[msg("Player limit reached.")]
    PlayerLimitReached,

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
fn mint_tokens_for_player(_dapp: &Account<Dapp>, player_name: &str, current_time: i64) -> Result<()> {
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
    _dapp_number: u32,
    _current_time: i64,
) -> Result<()> {
    // In reality you'd do leftover or map logic, then:
    // val_pda.last_minted = Some(_current_time);
    // val_pda.serialize back
    Ok(())
}
