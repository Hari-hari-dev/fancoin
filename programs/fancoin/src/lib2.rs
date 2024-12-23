use anchor_lang::prelude::*;
use sha3::{Digest, Keccak256};
use std::convert::TryInto;

declare_id!("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut");

const DECIMALS: u64 = 1_000_000_000; // 6 decimal places (unused in this code)

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct PlayerInfo {
    pub key: Pubkey,
    pub name: String,
}

#[program]
pub mod fancoin {
    use super::*;

    // ------------------------------------------------------------------
    //  Existing instructions
    // ------------------------------------------------------------------

    pub fn initialize_dapp(ctx: Context<InitializeDapp>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        dapp.owner = ctx.accounts.user.key();
        dapp.global_player_count = 0;
        Ok(())
    }

    pub fn relinquish_ownership(ctx: Context<RelinquishOwnership>) -> Result<()> {
        let dapp = &mut ctx.accounts.dapp;
        let signer = &ctx.accounts.signer;

        if dapp.owner != signer.key() {
            return Err(ErrorCode::Unauthorized.into());
        }

        dapp.owner = Pubkey::default();
        Ok(())
    }

    pub fn initialize_game(
        ctx: Context<InitializeGame>,
        game_number: u32,
        description: String
    ) -> Result<()> {
        let dapp = &ctx.accounts.dapp;
        let signer = &ctx.accounts.user;
        if dapp.owner != Pubkey::default() && dapp.owner != signer.key() {
            return Err(ErrorCode::Unauthorized.into());
        }

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
        game.player_count = 0;
        game.player_map = Vec::new();
        game.expanded = false;
        Ok(())
    }

    pub fn update_game_status(
        ctx: Context<UpdateGameStatus>,
        game_number: u32,
        new_status: u8,
        description: String
    ) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let dapp = &ctx.accounts.dapp;
        let signer = &ctx.accounts.signer;

        if dapp.owner != signer.key() {
            return Err(ErrorCode::Unauthorized.into());
        }

        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        if game.status != 0 {
            return Err(ErrorCode::GameStatusAlreadySet.into());
        }

        game.status = new_status;
        game.description = description;
        Ok(())
    }

    pub fn get_player_list(
        ctx: Context<GetPlayerList>,
        game_number: u32,
        start_index: u32,
        end_index: u32
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        let total_players = game.player_count;
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

        fn find_shard(shards: &Vec<Shard>, idx: u32) -> Option<usize> {
            let mut low = 0;
            let mut high = shards.len();
            while low < high {
                let mid = (low + high) / 2;
                let shard = &shards[mid];
                let start_range = shard.base_count;
                let end_range = shard.base_count + shard.local_count;

                if idx < start_range {
                    high = mid;
                } else if idx >= end_range {
                    low = mid + 1;
                } else {
                    return Some(mid);
                }
            }
            None
        }

        let mut current_idx = start_index;
        while current_idx < clamped_end {
            let shard_idx = match find_shard(&game.shards, current_idx) {
                Some(i) => i,
                None => break,
            };
            let shard = &game.shards[shard_idx];

            let shard_start = shard.base_count;
            let offset_in_shard = current_idx - shard_start;

            let available_in_shard = shard.local_count.saturating_sub(offset_in_shard);
            let needed = clamped_end - current_idx;
            let to_print = std::cmp::min(available_in_shard, needed);

            for i in offset_in_shard..(offset_in_shard + to_print) {
                let global_index = shard_start + i;
                let pkey = shard.players[i as usize];
                if let Some(player_info) = game.player_map.iter().find(|pi| pi.key == pkey) {
                    msg!(
                        "Player {}: {} (Name: {})",
                        global_index,
                        pkey,
                        player_info.name
                    );
                } else {
                    msg!("Player {}: {} (No name found)", global_index, pkey);
                }
            }

            current_idx += to_print;
        }

        Ok(())
    }

    pub fn get_validator_list(
        ctx: Context<GetValidatorList>,
        game_number: u32,
        start_index: u32,
        end_index: u32
    ) -> Result<()> {
        let game = &ctx.accounts.game;
        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        let total_validators = game.validators.len() as u32;
        if start_index >= total_validators
            || end_index > total_validators
            || start_index > end_index
        {
            return Err(ErrorCode::InvalidRange.into());
        }

        for i in start_index..end_index {
            let v = &game.validators[i as usize];
            msg!("Validator {}: {}", i, v.address);
        }

        Ok(())
    }

    // -----------
    // Existing change_player_name - no cooldown in the old code except one week.
    // -----------
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

        if let Some(existing_validator) = game
            .validators
            .iter_mut()
            .find(|v| v.address == validator_key)
        {
            existing_validator.last_activity = current_time;
        } else {
            game.validators.push(Validator {
                address: validator_key,
                last_activity: current_time,
            });
        }

        let seed_data = validator_key.to_bytes();
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

    // ------------------------------------------------------------------
    // register_player + debug
    // ------------------------------------------------------------------

    pub fn register_player(
        ctx: Context<RegisterPlayer>,
        game_number: u32,
        name: String,
        reward_address: Pubkey
    ) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let player_account = &mut ctx.accounts.player;
        let user = &ctx.accounts.user;

        if game.game_number != game_number {
            return Err(ErrorCode::GameNumberMismatch.into());
        }

        if game.status == 2 {
            return Err(ErrorCode::GameIsBlacklisted.into());
        }

        // Before adding player, ensure there's space in the game account
        let game_info = game.to_account_info();
        let user_info = user.to_account_info();
        add_space_and_fund(&game_info, &user_info, 2170)?;

        player_account.name = name.clone();
        player_account.address = user.key();
        player_account.reward_address = reward_address;
        player_account.last_minted = None;
        player_account.last_name_change = None;
        player_account.last_reward_address_change = None;

        let shard_capacity = 3;
        if game.shards.is_empty() || game.shards.last().unwrap().local_count >= shard_capacity {
            let new_shard = Shard {
                players: vec![player_account.key()],
                base_count: game.player_count,
                local_count: 1,
            };
            game.shards.push(new_shard);
        } else {
            let last_shard = game.shards.last_mut().unwrap();
            last_shard.players.push(player_account.key());
            last_shard.local_count += 1;
        }

        game.player_count += 1;

        // Set player_info_acc fields
        let player_info_acc = &mut ctx.accounts.player_info_acc;
        player_info_acc.key = player_account.key();
        player_info_acc.name = name;
        // If you wanted to store authority or anything else, you can add it here
        // currently it just has a 'key' and 'name' and 'authority'.

        Ok(())
    }
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
    pub fn register_player_debug(
        ctx: Context<RegisterPlayerDebug>,
        game_number: u32,
        name: String,
        reward_address: Pubkey,
        player_authority: Pubkey
    ) -> Result<()> {
        let game = &mut ctx.accounts.game;
        let player_account = &mut ctx.accounts.player;
        let player_info_acc = &mut ctx.accounts.player_info_acc;
        let user = &ctx.accounts.user;
    
        // ----- Checks -----
        if game.game_number != game_number {
            return err!(ErrorCode::GameNumberMismatch);
        }
        if game.status == 2 {
            return err!(ErrorCode::GameIsBlacklisted);
        }
    
        // ----- Optional: expand + fund the Game account -----
        // This step ensures the Game account has enough space to store new shards, etc.
        let game_info = game.to_account_info();
        let user_info = user.to_account_info();
        add_space_and_fund(&game_info, &user_info, 2170)?;
    
        // ----- Fill the Player account fields (just like register_player does) -----
        player_account.name = name.clone();
        // Optionally, you can use `user.key()` as the main address; 
        // for debugging, you might treat `reward_address` as the main address:
        //   player_account.address = user.key();
        //   player_account.reward_address = reward_address;
        // or keep it as is:
        player_account.address = reward_address;       
        player_account.reward_address = reward_address;
        player_account.last_minted = None;
        player_account.last_name_change = None;
        player_account.last_reward_address_change = None;
    
        // ----- Insert into shards -----
        let shard_capacity = 3;
        if game.shards.is_empty() || game.shards.last().unwrap().local_count >= shard_capacity {
            let new_shard = Shard {
                players: vec![player_account.key()],
                base_count: game.player_count,
                local_count: 1,
            };
            game.shards.push(new_shard);
        } else {
            let last_shard = game.shards.last_mut().unwrap();
            last_shard.players.push(player_account.key());
            last_shard.local_count += 1;
        }
    
        // ----- Bump the total player_count -----
        game.player_count += 1;
    
        // ----- Optionally, if you also want to store in `game.player_map`: -----
        // game.player_map.push(PlayerInfo {
        //     key: player_account.key(),
        //     name: name.clone(),
        // });
    
        // ----- Fill in PlayerInfoAccount so get_player_list can print the name -----
        player_info_acc.key = player_account.key();
        player_info_acc.name = name;
        player_info_acc.authority = player_authority;
    
        Ok(())
    }
    
    pub fn register_validator_pda(
        ctx: Context<RegisterValidatorPda>,
        game_number: u32,
    ) -> Result<()> {
        let game = &mut ctx.accounts.game;
        require!(game.game_number == game_number, ErrorCode::GameNumberMismatch);

        let val_pda = &mut ctx.accounts.validator_pda;
        let clock = Clock::get()?;

        val_pda.address = ctx.accounts.user.key();
        val_pda.last_activity = clock.unix_timestamp;

        // Increment the game’s validator_count
        game.validator_count += 1;
        Ok(())
    }

    // ------------------------------------------------------------------
    // Example of name + reward cooldown updates
    // ------------------------------------------------------------------
    pub fn update_player_name_cooldown(ctx: Context<UpdatePlayerNameCooldown>, new_name: String) -> Result<()> {
        let player = &mut ctx.accounts.player_pda;
        let clock = Clock::get()?;
        let now = clock.unix_timestamp;
        let one_week = 7 * 24 * 3600;

        // Check authority
        require!(player.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);

        // Check cooldown
        if let Some(last_change) = player.last_name_change {
            require!(now - last_change >= one_week, ErrorCode::NameChangeCooldown);
        }

        player.name = new_name;
        player.last_name_change = Some(now);
        Ok(())
    }

    /// Similar approach for reward address updates, if desired.
    pub fn update_player_reward_cooldown(ctx: Context<UpdatePlayerRewardCooldown>, new_reward: Pubkey) -> Result<()> {
        let player = &mut ctx.accounts.player_pda;
        let clock = Clock::get()?;
        let now = clock.unix_timestamp;
        let one_week = 7 * 24 * 3600;

        require!(player.authority == ctx.accounts.user.key(), ErrorCode::Unauthorized);

        if let Some(last_change) = player.last_reward_change {
            require!(now - last_change >= one_week, ErrorCode::NameChangeCooldown);
        }

        player.reward_address = new_reward;
        player.last_reward_change = Some(now);
        Ok(())
    }
    /// Change a player's name with a 1-week cooldown
    // pub fn update_player_name_cooldown(ctx: Context<UpdatePlayerNameCooldown>, new_name: String) -> Result<()> {
    //     let player = &mut ctx.accounts.player;
    //     let clock = Clock::get()?;
    //     let now = clock.unix_timestamp;
    //     let cooldown_seconds = 7 * 24 * 3600; // 1 week

    //     if let Some(last_change) = player.last_name_change {
    //         let elapsed = now - last_change;
    //         if elapsed < cooldown_seconds {
    //             return Err(ErrorCode::NameChangeCooldown.into());
    //         }
    //     }

    //     player.name = new_name;
    //     player.last_name_change = Some(now);
    //     Ok(())
    // }

    // /// Change a player's reward address with a 1-week cooldown
    // pub fn update_reward_address_cooldown(ctx: Context<UpdateRewardAddressCooldown>, new_reward: Pubkey) -> Result<()> {
    //     let player = &mut ctx.accounts.player;
    //     let clock = Clock::get()?;
    //     let now = clock.unix_timestamp;
    //     let cooldown_seconds = 7 * 24 * 3600; // 1 week

    //     if let Some(last_change) = player.last_reward_address_change {
    //         let elapsed = now - last_change;
    //         if elapsed < cooldown_seconds {
    //             // or define a new error if you want
    //             return Err(ErrorCode::NameChangeCooldown.into());
    //         }
    //     }

    //     player.reward_address = new_reward;
    //     player.last_reward_address_change = Some(now);
    //     Ok(())
    // }

    // ------------------------------------------------------------------
    // Submit Minting List (unchanged)
    // ------------------------------------------------------------------
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
            if let Some(agreement) = game
                .minting_agreements
                .iter_mut()
                .find(|ma| ma.player_name == player_name)
            {
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

        // Actually do the mints
        for player_name in successful_mints {
            mint_tokens_for_player(game, &player_name, current_time)?;
        }

        // Reward each validator
        for (validator_key, reward) in validator_rewards {
            mint_tokens(game, &validator_key, reward);
        }

        game.minting_agreements = remaining_agreements;
        Ok(())
    }
}

// ------------------------------------------------------------------
// Accounts + State
// ------------------------------------------------------------------

#[account]
pub struct PlayerInfoAccount {
    pub key: Pubkey,      // The 'player' account key
    pub name: String,     // The name
    pub authority: Pubkey // Additional stable key, if desired
}

// Optionally if you want name-based PDAs
#[account]
pub struct NameMap {
    pub user_address: Pubkey,
    pub name: String,
}

impl NameMap {
    pub const MAX_NAME_LEN: usize = 32;
    pub const LEN: usize = 8 // disc.
        + 32 // user_address
        + 4 + Self::MAX_NAME_LEN; // name
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
    // e.g. 8 disc + (4+32) name + 32 + 32 + 9 + 9 = ~ 122
    pub const LEN: usize = 8 
        + (4 + 32) 
        + 32 
        + 32 
        + 9 
        + 9;
}

/// A minimal Validator PDA for each game. Freed from big arrays in the Game.
#[account]
pub struct ValidatorPda {
    pub address: Pubkey,
    pub last_activity: i64,
}
impl ValidatorPda {
    // 8 disc + 32 + 8 = 48
    pub const LEN: usize = 8 + 32 + 8;
}


#[derive(Accounts)]
pub struct InitializeDapp<'info> {
    #[account(init, payer = user, space = DApp::LEN, seeds = [b"dapp"], bump)]
    pub dapp: Account<'info, DApp>,

    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
pub struct Initialize<'info> {
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

// Original name-changer
#[derive(Accounts)]
#[instruction()]
pub struct ChangePlayerName<'info> {
    #[account(mut)]
    pub player: Account<'info, Player>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

// Additional instructions for cooldown updates
#[derive(Accounts)]
pub struct UpdatePlayerNameCooldown<'info> {
    #[account(mut)]
    pub player: Account<'info, Player>,
    #[account(mut)]
    pub user: Signer<'info>,
}

#[derive(Accounts)]
pub struct UpdateRewardAddressCooldown<'info> {
    #[account(mut)]
    pub player: Account<'info, Player>,
    #[account(mut)]
    pub user: Signer<'info>,
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

// The main register instruction
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct RegisterPlayer<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    #[account(init, payer = user, space = Player::LEN)]
    pub player: Account<'info, Player>,

    #[account(
        init,
        payer = user,
        space = PlayerInfoAccount::LEN,
        seeds = [b"player_info", &game_number.to_le_bytes()[..], &game.player_count.to_le_bytes()],
        bump
    )]
    pub player_info_acc: Account<'info, PlayerInfoAccount>,

    #[account(mut)]
    pub user: Signer<'info>,

    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
#[instruction(
    game_number: u32,
    name: String,
    reward_address: Pubkey,
    player_authority: Pubkey
)]
pub struct RegisterPlayerDebug<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    #[account(init, payer = user, space = Player::LEN)]
    pub player: Account<'info, Player>,

    // We auto-init PlayerInfoAccount using seeds = [b"player_info", player_authority.as_ref()]
    #[account(
        init,
        payer = user,
        space = PlayerInfoAccount::LEN,
        seeds = [b"player_info", player_authority.as_ref()],
        bump
    )]
    pub player_info_acc: Account<'info, PlayerInfoAccount>,

    #[account(mut)]
    pub user: Signer<'info>,

    pub system_program: Program<'info, System>,
}



#[derive(Accounts)]
#[instruction(stable_key: Pubkey, name: String)]
pub struct RegisterPlayerName<'info> {
    #[account(
        init,
        payer = user,
        space = NameMap::LEN,
        seeds = [b"player_name", stable_key.as_ref(), name.as_bytes()],
        bump
    )]
    pub name_map: Account<'info, NameMap>,

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

// ------------------------------------------------------------------
// State: DApp, Game, Player, etc.
// ------------------------------------------------------------------

#[account]
pub struct DApp {
    pub owner: Pubkey,
    /// The total number of players ever registered across *all* games
    pub global_player_count: u32,
}
impl DApp {
    pub const LEN: usize = 8  // anchor disc
        + 32  // owner
        + 4;  // global_player_count
}

#[account]
pub struct Game {
    pub game_number: u32,
    pub validator_count: u32,
    pub status: u8,
    pub description: String,
    // Example fields that remain:
    pub last_seed: Option<u64>,
    pub last_punch_in_time: Option<i64>,
}
impl Game {
    // Just estimate space:
    // 8 disc + 4 + 4 + 1 + (4 + ~64) + 9 + 9 = ~ 99
    pub const LEN: usize = 8 + (4 + 4 + 1) + (4 + 64) + 9 + 9;
}


// #[account]
// pub struct Game {
//     pub game_number: u32,
//     pub status: u8,
//     pub description: String,
//     pub validators: Vec<Validator>,
//     pub shards: Vec<Shard>,
//     pub token_balances: Vec<TokenBalance>,
//     pub total_token_supply: u64,
//     pub last_seed: Option<u64>,
//     pub last_punch_in_time: Option<i64>,
//     pub minting_agreements: Vec<MintingAgreement>,
//     pub prefix_sums: Vec<u32>,
//     pub player_count: u32,
//     pub player_map: Vec<PlayerInfo>,
//     pub expanded: bool,
// }
// impl Game {
//     pub const BASE_LEN: usize = 8
//         + 4
//         + 1
//         + (4 + 64)
//         + 8
//         + 9
//         + 9
//         + 1;
// }

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
    pub name: String,                    // Up to 16 bytes
    pub address: Pubkey,                 // The player's main address
    pub reward_address: Pubkey,          // Where rewards go
    pub last_minted: Option<i64>,        // When they last minted
    pub last_name_change: Option<i64>,   // For cooldown logic
    pub last_reward_address_change: Option<i64>, // For reward address cooldown
}

impl Player {
    pub const MAX_NAME_LEN: usize = 16;
    pub const LEN: usize = 4 + Self::MAX_NAME_LEN
        + 32
        + 32
        + 9
        + 9
        + 9;
}

impl PlayerInfoAccount {
    pub const MAX_NAME_LEN: usize = 32;
    pub const LEN: usize = 8    // Anchor discriminator
        + 32                    // key
        + (4 + Self::MAX_NAME_LEN) // name
        + 32;                   // authority
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Shard {
    pub players: Vec<Pubkey>,
    pub base_count: u32,
    pub local_count: u32,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct TokenBalance {
    pub address: Pubkey,
    pub balance: u64,
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
#[derive(Accounts)]
#[instruction(game_number: u32)]
pub struct RegisterValidatorPda<'info> {
    #[account(mut, seeds = [b"game", &game_number.to_le_bytes()], bump)]
    pub game: Account<'info, Game>,

    #[account(
        init,
        payer = user,
        // we use game.validator_count as the index
        space = ValidatorPda::LEN,
        seeds = [
            b"validator",
            &game_number.to_le_bytes()[..],
            &game.validator_count.to_le_bytes()[..]
        ],
        bump
    )]
    pub validator_pda: Account<'info, ValidatorPda>,

    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

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
            &dapp.global_player_count.to_le_bytes()
        ],
        bump
    )]
    pub player_pda: Account<'info, PlayerPda>,

    #[account(mut)]
    pub user: Signer<'info>,

    pub system_program: Program<'info, System>,
}

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

// ------------------------------------------------------------------
// Utility
// ------------------------------------------------------------------

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
        let transfer_ix =
            anchor_lang::solana_program::system_instruction::transfer(user_info.key, game_info.key, required_lamports);
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

fn mint_tokens_for_player(_game: &mut Account<Game>, _player_name: &str, _current_time: i64) -> Result<()> {
    // No-op in your code. Insert logic if you need
    Ok(())
}

fn mint_tokens(game: &mut Account<Game>, address: &Pubkey, amount: u64) {
    if let Some(balance_entry) = game
        .token_balances
        .iter_mut()
        .find(|tb| tb.address == *address)
    {
        balance_entry.balance = balance_entry.balance.saturating_add(amount);
    } else {
        game.token_balances.push(TokenBalance {
            address: *address,
            balance: amount,
        });
    }
    game.total_token_supply = game.total_token_supply.saturating_add(amount);
}

pub fn get_validator_info(ctx: Context<GetValidatorList>, validator: Pubkey) -> Result<()> {
    let game = &ctx.accounts.game;
    let seed = game.last_seed.ok_or(ErrorCode::NoSeed)?;
    let group_id = calculate_group_id(&validator, seed)?;

    emit!(ValidatorInfoEvent { seed, group_id });
    Ok(())
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

#[event]
pub struct ValidatorInfoEvent {
    pub seed: u64,
    pub group_id: u64,
}
