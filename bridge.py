from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware #Necessary for POA chains
from datetime import datetime
import json
import pandas as pd


def connect_to(chain):
    if chain == 'source':  # The source contract chain is avax
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc" #AVAX C-chain testnet

    if chain == 'destination':  # The destination contract chain is bsc
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/" #BSC testnet

    if chain in ['source','destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        # inject the poa compatibility middleware to the innermost layer
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    """
        Load the contract_info file into a dictionary
        This function is used by the autograder and will likely be useful to you
    """
    try:
        with open(contract_info, 'r')  as f:
            contracts = json.load(f)
    except Exception as e:
        print( f"Failed to read contract info\nPlease contact your instructor\n{e}" )
        return 0
    return contracts[chain]



def scan_blocks(chain, contract_info="contract_info.json"):
    """
        chain - (string) should be either "source" or "destination"
        Scan the last 5 blocks of the source and destination chains
        Look for 'Deposit' events on the source chain and 'Unwrap' events on the destination chain
        When Deposit events are found on the source chain, call the 'wrap' function the destination chain
        When Unwrap events are found on the destination chain, call the 'withdraw' function on the source chain
    """

    # This is different from Bridge IV where chain was "avax" or "bsc"
    if chain not in ['source','destination']:
        print( f"Invalid chain: {chain}" )
        return 0
    
        #YOUR CODE HERE
    w3_source = connect_to('source')
    w3_destination = connect_to('destination')

    source_info = get_contract_info('source', contract_info)
    destination_info = get_contract_info('destination', contract_info)

    source_contract = w3_source.eth.contract(address=source_info['address'], abi=source_info['abi'])
    destination_contract = w3_destination.eth.contract(address=destination_info['address'], abi=destination_info['abi'])

    # pull signer creds (prefer top-level; fallback to per-chain if needed)
    with open(contract_info, 'r') as f:
        ci_all = json.load(f)

    wallet_address = (ci_all.get('signer')
                      or source_info.get('signer')
                      or destination_info.get('signer'))
    private_key = (ci_all.get('signer_key')
                   or source_info.get('signer_key')
                   or destination_info.get('signer_key'))

    # validate signer info
    if not wallet_address or not isinstance(wallet_address, str):
        print("ERROR: 'signer' missing or invalid in contract_info.json (top-level or per-chain).")
        return 0
    if not private_key or not isinstance(private_key, str):
        print("ERROR: 'signer_key' missing or invalid in contract_info.json (top-level or per-chain).")
        return 0

    wallet_address = wallet_address.strip()
    private_key = private_key.strip()

    # choose which events to read and which chain to send txs on
    if chain == 'source':
        # listen on source for Deposit; send tx on destination -> wrap()
        from_block = max(0, w3_source.eth.block_number - 5)
        event_filter = source_contract.events.Deposit.create_filter(from_block=from_block)
        tx_w3 = w3_destination
        tx_contract = destination_contract
        action = 'wrap'
    else:
        # listen on destination for Unwrap; send tx on source -> withdraw()
        from_block = max(0, w3_destination.eth.block_number - 5)
        event_filter = destination_contract.events.Unwrap.create_filter(from_block=from_block)
        tx_w3 = w3_source
        tx_contract = source_contract
        action = 'withdraw'

    # fetch events once to avoid rate limits
    events = event_filter.get_all_entries()

    for event in events:
        # always use pending nonce so we can batch safely
        nonce = tx_w3.eth.get_transaction_count(wallet_address, 'pending')
        gas_price = int(tx_w3.eth.gas_price * 1.2)

        if chain == 'source' and action == 'wrap':
            # Deposit(token, recipient, amount) -> Destination.wrap(token, recipient, amount)
            txn = tx_contract.functions.wrap(
                event['args']['token'],
                event['args']['recipient'],
                event['args']['amount']
            ).build_transaction({
                'from': wallet_address,
                'chainId': tx_w3.eth.chain_id,
                'gas': 700000,
                'nonce': nonce,
                'gasPrice': gas_price
            })
        elif chain == 'destination' and action == 'withdraw':
            # Unwrap(underlying, wrapped, frm, to, amount) -> Source.withdraw(underlying, to, amount)
            txn = tx_contract.functions.withdraw(
                event['args']['underlying_token'],
                event['args']['to'],
                event['args']['amount']
            ).build_transaction({
                'from': wallet_address,
                'chainId': tx_w3.eth.chain_id,
                'gas': 700000,
                'nonce': nonce,
                'gasPrice': gas_price
            })
        else:
            continue

        signed = tx_w3.eth.account.sign_transaction(txn, private_key=private_key)
        tx_w3.eth.send_raw_transaction(signed.raw_transaction)
