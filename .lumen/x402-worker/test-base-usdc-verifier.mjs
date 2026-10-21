import assert from "node:assert/strict";
import {verifyBaseUsdcTransfer} from "./base-usdc-verifier.js";
const tx="0x"+"a".repeat(64),recipient="0x"+"b".repeat(40);
const topic="0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const receipt={status:"0x1",transactionHash:tx,blockHash:"0x"+"c".repeat(64),blockNumber:"0x64",logs:[{address:"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",removed:false,topics:[topic,"0x"+"0".repeat(64),"0x"+recipient.slice(2).padStart(64,"0")],data:"0x4c4b40",logIndex:"0x1"}]};
function mock(chain="0x2105",r=receipt,block="0x80"){return async(_url,opts)=>{const {method}=JSON.parse(opts.body);return {ok:true,json:async()=>({result:method==="eth_chainId"?chain:method==="eth_blockNumber"?block:r})};};}
const input={rpcUrl:"https://example.invalid",transaction:tx,recipient,amountUsd:5};
assert.equal((await verifyBaseUsdcTransfer({...input,fetchImpl:mock()})).ok,true);
assert.equal((await verifyBaseUsdcTransfer({...input,fetchImpl:mock("0x1")})).ok,false);
assert.equal((await verifyBaseUsdcTransfer({...input,fetchImpl:mock("0x2105",{...receipt,status:"0x0"})})).ok,false);
assert.equal((await verifyBaseUsdcTransfer({...input,fetchImpl:mock("0x2105",receipt,"0x65")})).ok,false);
assert.equal((await verifyBaseUsdcTransfer({...input,recipient:"0x"+"d".repeat(40),fetchImpl:mock()})).ok,false);
assert.equal((await verifyBaseUsdcTransfer({...input,amountUsd:7,fetchImpl:mock()})).ok,false);
assert.equal((await verifyBaseUsdcTransfer({...input,fetchImpl:mock("0x2105",receipt,"0x63")})).ok,false);
assert.equal((await verifyBaseUsdcTransfer({...input,fetchImpl:mock("0x2105",{...receipt,logs:[...receipt.logs,...receipt.logs]})})).ok,false);
console.log("BASE_USDC_VERIFIER_TESTS_OK");
