const fs = require('fs');
const path = require('path');
const {
  Connection,
  Keypair,
  clusterApiUrl,
  LAMPORTS_PER_SOL,
  SystemProgram,
  Transaction,
  PublicKey,
} = require('@solana/web3.js');

// Load the user's keypair from the file specified by ANCHOR_WALLET
function loadKeypair() {
  const walletPath = process.env.ANCHOR_WALLET;
  if (!walletPath) {
    throw new Error("ANCHOR_WALLET environment variable not set");
  }
  const secretKey = Uint8Array.from(JSON.parse(fs.readFileSync(walletPath, 'utf8')));
  return Keypair.fromSecretKey(secretKey);
}

(async () => {
  // Connect to localnet
  const connection = new Connection("http://127.0.0.1:8899", 'confirmed');

  // Load user's keypair
  const userKeypair = loadKeypair();
  const userPubkey = userKeypair.publicKey;

  // Your program ID
  const programId = new PublicKey("HP9ucKGU9Sad7EaWjrGULC2ZSyYD1ScxVPh15QmdRmut");

  // Derive the PDA for game_number = 1
  const gameNumber = 1;
  const [gamePda, gameBump] = await PublicKey.findProgramAddress(
    [Buffer.from("game"), Buffer.from(new Uint8Array(new Uint32Array([gameNumber]).buffer))],
    programId
  );

  console.log("Game PDA:", gamePda.toBase58());

  // Preallocate space (e.g. 15000 bytes as discussed)
  const space = 15000;

  // Calculate minimum lamports for rent exemption
  const rentExemptionLamports = await connection.getMinimumBalanceForRentExemption(space);

  // Create the game account via SystemProgram.createAccount
  const createAccountIx = SystemProgram.createAccount({
    fromPubkey: userPubkey,
    newAccountPubkey: gamePda,
    lamports: rentExemptionLamports,
    space: space,
    programId: programId,
  });

  // Build a transaction
  let tx = new Transaction().add(createAccountIx);

  // Fetch recent blockhash
  let { blockhash } = await connection.getLatestBlockhash();
  tx.recentBlockhash = blockhash;
  tx.feePayer = userPubkey;

  // Since this is a PDA derived account, you do NOT add a signature for the PDA
  // Only the user (payer) signs the transaction
  tx.sign(userKeypair);

  // Send and confirm the transaction
  const txSig = await connection.sendTransaction(tx, [userKeypair], { skipPreflight: false });
  console.log("Game account creation transaction signature:", txSig);

  // Confirm the transaction
  await connection.confirmTransaction(txSig, 'confirmed');
  console.log("Game account created successfully. You can now call initialize_game separately.");
})();
