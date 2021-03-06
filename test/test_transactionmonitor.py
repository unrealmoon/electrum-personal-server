
import pytest

from electrumpersonalserver import (DeterministicWallet, TransactionMonitor,
                                JsonRpcError, script_to_scripthash)

class DummyJsonRpc(object):
    def __init__(self, txlist, utxoset, block_heights):
        self.txlist = txlist
        self.utxoset = utxoset
        self.block_heights = block_heights
        self.imported_addresses = []

    def call(self, method, params):
        if method == "listtransactions":
            count = int(params[1])
            skip = int(params[2])
            return self.txlist[skip:skip + count]
        elif method == "gettransaction":
            for t in self.txlist:
                if t["txid"] == params[0]:
                    return t
            raise JsonRpcError()
        elif method == "decoderawtransaction":
            for t in self.txlist:
                if t["hex"] == params[0]:
                    return t
            assert 0
        elif method == "gettxout":
            for u in self.utxoset:
                if u["txid"] == params[0] and u["vout"] == params[1]:
                    return u
            assert 0
        elif method == "getblockheader":
            if params[0] not in self.block_heights:
                assert 0
            return {"height": self.block_heights[params[0]]}
        elif method == "decodescript":
            return {"addresses": [dummy_spk_to_address(params[0])]}
        elif method == "importaddress":
            self.imported_addresses.append(params[0])
        else:
            raise ValueError("unknown method in dummy jsonrpc")

    def add_transaction(self, tx):
        self.txlist.append(tx)

    def get_imported_addresses(self):
        return self.imported_addresses


class DummyDeterministicWallet(DeterministicWallet):
    """Empty deterministic wallets"""
    def __init__(self):
        pass

    def have_scriptpubkeys_overrun_gaplimit(self, scriptpubkeys):
        return None #not overrun

    def get_new_scriptpubkeys(self, change, count):
        pass


def dummy_spk_to_address(spk):
    return spk + "-address"

debugf = lambda x: print("[DEBUG] " + x)
logf = lambda x: print("[  LOG] " + x)

deterministic_wallets = [DummyDeterministicWallet()]
dummy_id_g = [1000]

def create_dummy_spk(): #script pub key
    dummy_id = dummy_id_g[0]
    dummy_id_g[0] += 1
    return "deadbeef" + str(dummy_id)

def create_dummy_funding_tx(confirmations=1, output_spk=None,
        input_txid="placeholder-unknown-input-txid"):
    dummy_id = dummy_id_g[0]
    dummy_id_g[0] += 1

    if output_spk == None:
        dummy_spk = "deadbeef" + str(dummy_id) #scriptpubkey
    else:
        dummy_spk = output_spk
    dummy_containing_block = "blockhash-placeholder" + str(dummy_id)
    containing_block_height = dummy_id
    dummy_tx = {
        "txid": "placeholder-test-txid" + str(dummy_id),
        "vin": [{"txid": input_txid, "vout": 0, "value": 1,
            "confirmations": 1}],
        "vout": [{"value": 1, "scriptPubKey": {"hex": dummy_spk}}],
        "address": dummy_spk_to_address(dummy_spk),
        "category": "receive",
        "confirmations": confirmations,
        "blockhash": dummy_containing_block,
        "hex": "placeholder-test-txhex" + str(dummy_id)
    }
    return dummy_spk, containing_block_height, dummy_tx

def assert_address_history_tx(address_history, spk, height, txid, subscribed):
    history_element = address_history[script_to_scripthash(spk)]
    assert history_element["history"][0]["height"] == height
    assert history_element["history"][0]["tx_hash"] == txid
    #fee always zero, its easier to test because otherwise you have
    # to use Decimal to stop float weirdness
    if height == 0:
        assert history_element["history"][0]["fee"] == 0
    assert history_element["subscribed"] == subscribed

def test_single_tx():
    ###single confirmed tx in wallet belonging to us, address history built
    dummy_spk, containing_block_height, dummy_tx = create_dummy_funding_tx()

    rpc = DummyJsonRpc([dummy_tx], [],
        {dummy_tx["blockhash"]: containing_block_height})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk])
    assert len(txmonitor.address_history) == 1
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk,
        height=containing_block_height, txid=dummy_tx["txid"], subscribed=False)

def test_two_txes():
    ###two confirmed txes in wallet belonging to us, addr history built
    dummy_spk1, containing_block_height1, dummy_tx1 = create_dummy_funding_tx()
    dummy_spk2, containing_block_height2, dummy_tx2 = create_dummy_funding_tx()

    rpc = DummyJsonRpc([dummy_tx1, dummy_tx2], [],
        {dummy_tx1["blockhash"]: containing_block_height1,
        dummy_tx2["blockhash"]: containing_block_height2})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk1, dummy_spk2])
    assert len(txmonitor.address_history) == 2
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk1,
        height=containing_block_height1, txid=dummy_tx1["txid"],
        subscribed=False)
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk2,
        height=containing_block_height2, txid=dummy_tx2["txid"],
        subscribed=False)

def test_non_subscribed_confirmation():
    ###one unconfirmed tx in wallet belonging to us, with confirmed inputs,
    ### addr history built, then tx confirms, not subscribed to address
    dummy_spk, containing_block_height, dummy_tx = create_dummy_funding_tx(
        confirmations=0)

    rpc = DummyJsonRpc([dummy_tx], [dummy_tx["vin"][0]],
        {dummy_tx["blockhash"]: containing_block_height})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk])
    assert len(txmonitor.address_history) == 1
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk,
        height=0, txid=dummy_tx["txid"], subscribed=False)
    assert len(list(txmonitor.check_for_updated_txes())) == 0
    dummy_tx["confirmations"] = 1 #tx confirms
    #not subscribed so still only returns an empty list
    assert len(list(txmonitor.check_for_updated_txes())) == 0
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk,
        height=containing_block_height, txid=dummy_tx["txid"], subscribed=False)

def test_tx_arrival_then_confirmation():
    ###build empty address history, subscribe one address
    ### an unconfirmed tx appears, then confirms
    dummy_spk, containing_block_height, dummy_tx = create_dummy_funding_tx(
        confirmations=0)

    rpc = DummyJsonRpc([], [dummy_tx["vin"][0]], {dummy_tx["blockhash"]:
        containing_block_height})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk])
    assert len(txmonitor.address_history) == 1
    sh = script_to_scripthash(dummy_spk)
    assert len(txmonitor.get_electrum_history(sh)) == 0
    txmonitor.subscribe_address(sh)
    # unconfirm transaction appears
    assert len(list(txmonitor.check_for_updated_txes())) == 0
    rpc.add_transaction(dummy_tx)
    assert len(list(txmonitor.check_for_updated_txes())) == 1
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk,
        height=0, txid=dummy_tx["txid"], subscribed=True)
    # transaction confirms
    dummy_tx["confirmations"] = 1
    assert len(list(txmonitor.check_for_updated_txes())) == 1
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk,
        height=containing_block_height, txid=dummy_tx["txid"], subscribed=True)

def test_unrelated_tx():
    ###transaction that has nothing to do with our wallet
    dummy_spk, containing_block_height, dummy_tx = create_dummy_funding_tx(
        confirmations=0)
    our_dummy_spk = create_dummy_spk()

    rpc = DummyJsonRpc([dummy_tx], [], {dummy_tx["blockhash"]:
        containing_block_height})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([our_dummy_spk])
    assert len(txmonitor.address_history) == 1
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        our_dummy_spk))) == 0

def test_address_reuse():
    ###transaction which arrives to an address which already has a tx on it
    dummy_spk1, containing_block_height1, dummy_tx1 = create_dummy_funding_tx()
    dummy_spk2, containing_block_height2, dummy_tx2 = create_dummy_funding_tx(
        output_spk=dummy_spk1)

    rpc = DummyJsonRpc([dummy_tx1], [], {dummy_tx1["blockhash"]:
        containing_block_height1, dummy_tx2["blockhash"]:
        containing_block_height2})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk1])
    sh = script_to_scripthash(dummy_spk1)
    assert len(txmonitor.get_electrum_history(sh)) == 1
    rpc.add_transaction(dummy_tx2)
    assert len(txmonitor.get_electrum_history(sh)) == 1
    txmonitor.check_for_updated_txes()
    assert len(txmonitor.get_electrum_history(sh)) == 2

def test_from_address():
    ###transaction spending FROM one of our addresses
    dummy_spk1, containing_block_height1, input_tx = create_dummy_funding_tx()
    dummy_spk2, containing_block_height2, spending_tx = create_dummy_funding_tx(
        input_txid=input_tx["txid"])

    rpc = DummyJsonRpc([input_tx, spending_tx], [],
        {input_tx["blockhash"]: containing_block_height1,
        spending_tx["blockhash"]: containing_block_height2})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk1])
    sh = script_to_scripthash(dummy_spk1)
    assert len(txmonitor.get_electrum_history(sh)) == 2

def test_tx_within_wallet():
    ###transaction from one address to the other, both addresses in wallet
    dummy_spk1, containing_block_height1, dummy_tx1 = create_dummy_funding_tx()
    dummy_spk2, containing_block_height2, dummy_tx2 = create_dummy_funding_tx(
        input_txid=dummy_tx1["txid"])

    rpc = DummyJsonRpc([dummy_tx1, dummy_tx2], [],
        {dummy_tx1["blockhash"]: containing_block_height1,
        dummy_tx2["blockhash"]: containing_block_height2})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk1, dummy_spk2])
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        dummy_spk1))) == 2
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        dummy_spk2))) == 1

def test_overrun_gap_limit():
    ###overrun gap limit so import address is needed
    dummy_spk, containing_block_height, dummy_tx = create_dummy_funding_tx()
    dummy_spk_imported = create_dummy_spk()

    class DummyImportDeterministicWallet(DeterministicWallet):
        def __init__(self):
            pass

        def have_scriptpubkeys_overrun_gaplimit(self, scriptpubkeys):
            return {0: 1} #overrun by one

        def get_new_scriptpubkeys(self, change, count):
            return [dummy_spk_imported]

    rpc = DummyJsonRpc([], [], {dummy_tx["blockhash"]: containing_block_height})
    txmonitor = TransactionMonitor(rpc, [DummyImportDeterministicWallet()],
        debugf, logf)
    assert txmonitor.build_address_history([dummy_spk])
    assert len(txmonitor.address_history) == 1
    assert len(list(txmonitor.check_for_updated_txes())) == 0
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        dummy_spk))) == 0
    rpc.add_transaction(dummy_tx)
    assert len(list(txmonitor.check_for_updated_txes())) == 0
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        dummy_spk))) == 1
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        dummy_spk_imported))) == 0
    assert len(rpc.get_imported_addresses()) == 1
    assert rpc.get_imported_addresses()[0] == dummy_spk_to_address(
        dummy_spk_imported)

def test_conflicted_tx():
    ###conflicted transaction should get rejected
    dummy_spk, containing_block_height, dummy_tx = create_dummy_funding_tx(
        confirmations=-1)

    rpc = DummyJsonRpc([dummy_tx], [], {})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk])
    assert len(txmonitor.address_history) == 1
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        dummy_spk))) == 0 #shouldnt show up after build history b/c conflicted
    rpc.add_transaction(dummy_tx)
    assert len(list(txmonitor.check_for_updated_txes())) == 0
    assert len(txmonitor.get_electrum_history(script_to_scripthash(
        dummy_spk))) == 0 #incoming tx is not added too

def test_double_spend():
    ###an unconfirmed tx being broadcast, another conflicting tx being
    ### confirmed, the first tx gets conflicted status

    dummy_spk, containing_block_height1, dummy_tx1 = create_dummy_funding_tx(
        confirmations=0)
    dummy_spk_, containing_block_height2, dummy_tx2 = create_dummy_funding_tx(
        confirmations=0, input_txid=dummy_tx1["vin"][0], output_spk=dummy_spk)
    #two unconfirmed txes spending the same input, so they are in conflict

    rpc = DummyJsonRpc([dummy_tx1], [dummy_tx1["vin"][0]],
        {dummy_tx1["blockhash"]: containing_block_height1,
        dummy_tx2["blockhash"]: containing_block_height2})
    txmonitor = TransactionMonitor(rpc, deterministic_wallets, debugf, logf)
    assert txmonitor.build_address_history([dummy_spk])
    assert len(txmonitor.address_history) == 1
    sh = script_to_scripthash(dummy_spk)
    assert len(txmonitor.get_electrum_history(sh)) == 1
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk,
        height=0, txid=dummy_tx1["txid"], subscribed=False)
    # a conflicting transaction confirms
    rpc.add_transaction(dummy_tx2)
    dummy_tx1["confirmations"] = -1
    dummy_tx2["confirmations"] = 1
    assert len(list(txmonitor.check_for_updated_txes())) == 0
    assert len(txmonitor.get_electrum_history(sh)) == 1
    assert_address_history_tx(txmonitor.address_history, spk=dummy_spk,
        height=containing_block_height2, txid=dummy_tx2["txid"],
        subscribed=False)


#other possible stuff to test:
#finding confirmed and unconfirmed tx, in that order, then both confirm
#finding unconfirmed and confirmed tx, in that order, then both confirm

#tests about conflicts:
#build address history where reorgable txes are found
#an unconfirmed tx arrives, gets confirmed, reaches the safe threshold
#   and gets removed from list
#a confirmed tx arrives, reaches safe threshold and gets removed
#an unconfirmed tx arrives, confirms, gets reorgd out, returns to
#   unconfirmed
#an unconfirmed tx arrives, confirms, gets reorgd out and conflicted
#an unconfirmed tx arrives, confirms, gets reorgd out and confirmed at
#   a different height
#an unconfirmed tx arrives, confirms, gets reorgd out and confirmed in
#   the same height

