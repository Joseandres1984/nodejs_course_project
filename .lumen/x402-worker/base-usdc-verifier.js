// Independent Base mainnet USDC transfer proof. Fail closed on any uncertainty.
export const BASE_CHAIN_ID = "0x2105";
export const BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const address = x => /^0x[0-9a-fA-F]{40}$/.test(String(x||""));
const hash = x => /^0x[0-9a-fA-F]{64}$/.test(String(x||""));
const pad = x => "0x" + x.slice(2).toLowerCase().padStart(64,"0");
export async function verifyBaseUsdcTransfer({rpcUrl,transaction,recipient,amountUsd,fetchImpl=fetch}) {
  if (!/^https:\/\//.test(String(rpcUrl||"")) || !hash(transaction) || !address(recipient) || !Number.isSafeInteger(Number(amountUsd)*1e6) || Number(amountUsd)<=0) return {ok:false,reason:"invalid_verification_input"};
  const rpc=async(method,params)=>{
    const response=await fetchImpl(rpcUrl,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({jsonrpc:"2.0",id:1,method,params})});
    if(!response.ok) throw Error("rpc_http_error");
    const data=await response.json();
    if(data.error || !data.result) throw Error("rpc_invalid_response");
    return data.result;
  };
  try {
    const chain=await rpc("eth_chainId",[]);
    if(chain.toLowerCase()!==BASE_CHAIN_ID) return {ok:false,reason:"wrong_chain"};
    const receipt=await rpc("eth_getTransactionReceipt",[transaction]);
    if(receipt.status!=="0x1" || String(receipt.transactionHash).toLowerCase()!==transaction.toLowerCase() || !receipt.blockHash || !receipt.blockNumber) return {ok:false,reason:"unconfirmed_or_failed_transaction"};
    const current=BigInt(await rpc("eth_blockNumber",[]));
    if(current<BigInt(receipt.blockNumber) || current-BigInt(receipt.blockNumber)<12n) return {ok:false,reason:"insufficient_confirmations"};
    const expected=BigInt(Math.round(Number(amountUsd)*1e6));
    const matching=(receipt.logs||[]).filter(log=>String(log.address).toLowerCase()===BASE_USDC && log.removed!==true && Array.isArray(log.topics) && log.topics.length===3 && String(log.topics[0]).toLowerCase()===TRANSFER_TOPIC && String(log.topics[2]).toLowerCase()===pad(recipient) && /^0x[0-9a-fA-F]+$/.test(String(log.data||"")) && BigInt(log.data)===expected);
    if(matching.length!==1) return {ok:false,reason:"usdc_transfer_not_unique_or_missing"};
    if(!/^0x[0-9a-fA-F]+$/.test(String(matching[0].logIndex||""))) return {ok:false,reason:"missing_log_index"};
    return {ok:true,transaction:transaction.toLowerCase(),network:"eip155:8453",recipient:recipient.toLowerCase(),amountUsd:Number(amountUsd),blockNumber:receipt.blockNumber,logIndex:matching[0].logIndex};
  } catch {return {ok:false,reason:"rpc_verification_failed"};}
}
