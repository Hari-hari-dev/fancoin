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

  // Derive the PDA for dapp_number = 1
  const dappNumber = 1;
  const [dappPda, dappBump] = await PublicKey.findProgramAddress(
    [Buffer.from("dapp"), Buffer.from(new Uint8Array(new Uint32Array([dappNumber]).buffer))],
    programId
  );

  console.log("Dapp PDA:", dappPda.toBase58());

  // Preallocate space (e.g. 15000 bytes as discussed)
  const space = 15000;

  // Calculate minimum lamports for rent exemption
  const rentExemptionLamports = await connection.getMinimumBalanceForRentExemption(space);

  // Create the dapp account via SystemProgram.createAccount
  const createAccountIx = SystemProgram.createAccount({
    fromPubkey: userPubkey,
    newAccountPubkey: dappPda,
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
  console.log("Dapp account creation transaction signature:", txSig);

  // Confirm the transaction
  await connection.confirmTransaction(txSig, 'confirmed');
  console.log("Dapp account created successfully. You can now call initialize_dapp separately.");
})();
