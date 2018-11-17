# For Client Class -- Code from DAPs only
import asyncio
from aioconsole import ainput

import cryptography
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

import hashlib
import codecs
import base58
import pickle
import warnings

from helper import StupidPublicKey
from transactions import MoneyTransation
from block import Block
from block_chain import BlockChain

import time
import random

from aiohttp import web
import aiohttp_jinja2
import jinja2

class ClosingException(Exception):
    pass

class ServerClosingException(Exception):
    pass

class BlockChainClient:    
    def __init__(self, port, crypto_curve, signature_algo,start_reward, decrease_reward):

        self.PORT = port
        self.CURVE = crypto_curve
        self.SIGNATURE_ALGORITHM = signature_algo
        self.DECREASE_REWAD = decrease_reward

        self.reward = start_reward

        # Start generating private & public key
        self._private_key = ec.generate_private_key(self.CURVE, default_backend())
        self.public_key_obj = self._private_key.public_key()
        self.public_key = StupidPublicKey(self.public_key_obj.public_numbers().x,
                                            self.public_key_obj.public_numbers().y)

        self.address = self.generate_address()
        self.chain = BlockChain()
        self.mempool = []

        self.is_mining = False
        self.fucking_delay = 0

    async def send_to_server(self, server):
        while True:
            msg = await ainput('')
            if msg == None or msg == '':
                continue

            await self.parse_input(msg)

    async def get_data_server(self, server, client):
        while True:
            data = await client.read(4048)
            if server.transport.is_closing():
                print("Closing")

            if len(data) == 0:
                raise ServerClosingException()

            await self.parse_server_message(data)

    async def send_object_server(self, obj):
        self.server.write(pickle.dumps(obj))
        await self.server.drain()

    async def send_transations(self, address, value):
        # Check Address
        if address == self.address:
            print("That is your address")
        elif self.check_address(address):
            if not self.chain.get_money().get(self.address, 0) >= value:
                print("Not enough Fund LOL")
            else:
                message = {
                    "sender_address": self.address,
                    "public_key": self.public_key,
                    "receiver_address": address,
                    "value": value
                }

                sig = self._private_key.sign(pickle.dumps(message), self.SIGNATURE_ALGORITHM)
                send_object = MoneyTransation(message, sig)

                # Sending message
                await self.send_object_server(send_object)
        else:
            print("Address not correct")

    async def parse_input(self, command):
        data = command.split(' ')
        if data[0] == "pay":
            assert len(data) == 3

            address = data[1]
            value = float(data[2])

            await self.send_transations(address, value)

        elif data[0] == "show_chain":
            asyncio.ensure_future(self.print_chain())
        elif data[0] == "show_mempool":
            print(self.mempool)
        elif data[0] == "show_money":
            print(self.chain.get_money())
        else:
            print("Command not Found")

    async def print_chain(self):
        print(f"Count: {self.chain.data['count']}")
        for c in self.chain.data['content']:
            print('\n\n')
            print(c)
            await asyncio.sleep(0.0)

    async def parse_server_message(self, data):
        data = pickle.loads(data)

        if isinstance(data, MoneyTransation):
            # Start creating your own block
            if not self.check_signature(data.message, data.signature):
                print("Transaction Not accepted")
                return

            if self.is_mining:
                self.mempool.append(data)
            else:
                self.mempool.append(data)
                self.mempool.append(MoneyTransation.create_reward(self.address, self.reward))

                if self.check_multiple_transactions(self.mempool):
                    block = Block(self.chain.data['count'],
                                  time.time(),
                                  self.chain.data['content'][-1].header.self_hash(),
                                  self.mempool)

                    self.mempool = []
                    self.is_mining = True
                    self.mine_task = asyncio.ensure_future(self.mine(block))

        elif isinstance(data, str):
            if data == "FIRST_USER":
                print("God has chosen you to mine the genesis block")
                genesis_block = Block(0,
                                      time.time(),
                                      "0000000000000000000000000000000000000000000000000000000000000000",
                                      [MoneyTransation.create_reward(self.address, self.reward)])

                # Mine the block
                self.is_mining = True
                self.mine_task = asyncio.ensure_future(self.mine(genesis_block))

            if data == "REQUEST_BLOCKCHAIN":
                print("Requestion a blockchain")
                await self.send_object_server(self.chain)

        elif isinstance(data, Block):
            print("Get a block")
            if self.check_block(data):
                print("Add to the chain")
                self.chain.add_data(data)

                self.mine_task.cancel()
                self.is_mining = False
            else:
                print("Can't Add sth wrong")

        elif isinstance(data, BlockChain):
            if self.chain.data['count'] == 0:
                self.chain = data
                print("Chain Added")
        else:
            print("Getting Weird Object")
            print(data)

    async def mine(self, block):
        header = block.header
        num_zero = self.current_difficulty()
        warnings.warn("Haven't implementaed difficulty")

        block_hash = header.self_hash()
        while not block_hash[:num_zero] == '0' * num_zero:
            header.nouce += 1
            block_hash = header.self_hash()
            await asyncio.sleep(self.fucking_delay)

        block.header = header
        self.is_mining = False

        await self.send_object_server(block)

    def current_difficulty(self):
        return 4

    def check_address(self, address):
        # Just a wrapper
        try:
            base58.b58decode_check(address)
        except ValueError:
            return False
        else:
            return True

    def check_block(self, block):
        if not self.check_header(block.header):
            return False

        if not block.header.transaction_hash == block.transaction_list_hash():
            print("BLOCK: transaction hash are not the same.")
            return False

        # Check transaction money
        if not self.check_multiple_transactions(block.transaction_list):
            return False

        return True

    def check_header(self, header):
        if not header.index == self.chain.data['count']:
            print("HEADER: header index not currect")
            return False

        if not self.chain.data['count'] == 0:
            latest_head = self.chain.data['content'][-1].header
            if not latest_head.timestamp < header.timestamp:
                print("HEADER: wrong time stamp")
                return False

            if not latest_head.self_hash() == header.prev_hash:
                print("HEADER: wrong previous hash")
                return False

        # Check for PoW
        if not header.self_hash()[:self.current_difficulty()] == '0' * self.current_difficulty():
            print("HEADER: wrong proof of work")
            return False

        return True

    def check_multiple_transactions(self, transaction_list):
        # Checking for weird funds
        total_money = self.chain.get_money()
        change = self.chain.total_transaction_list(transaction_list)

        # Might be a problem of dropping everyting when one fail :(
        if any(total_money.get(addr, 0) + val < 0 for addr, val in change.items()):
            print("LIST TRANSACTION: run out of funds")
            return False

        if not all(self.check_signature(t.message, t.signature) for t in transaction_list):
            print("LIST TRANSACTION: wrong signature")
            return False

        return True

    async def start_connection(self, server, client):
        await asyncio.gather(self.get_data_server(server, client), self.send_to_server(server))

    async def open_connection(self, loop):
        client, server = await asyncio.open_connection('127.0.0.1',
                                                         8888,loop=loop)
        return client, server

    def check_signature(self, message, signature):
        byte_message = pickle.dumps(message)

        if message['sender_address'] == "system":
            return True

        pub = ec.EllipticCurvePublicNumbers(
                message['public_key'].x,
                message['public_key'].y,
                self.CURVE
            ).public_key(default_backend())

        try:
            pub.verify(signature, byte_message, self.SIGNATURE_ALGORITHM)
        except cryptography.exceptions.InvalidSignature:
            return False
        else:
            return True

    def generate_address(self):
        # Using the hash stuff from bitcoin wiki
        actual_key = '02' + format(self.public_key.x, '064x')

        sh = hashlib.sha256()
        rip = hashlib.new('ripemd160')

        sh.update(codecs.decode(actual_key, 'hex'))
        rip.update(sh.digest())

        double_hash = '00' + rip.hexdigest()
        sh.update(codecs.decode(double_hash, 'hex'))

        check_sum_1 = hashlib.sha256(codecs.decode(double_hash, 'hex'))
        check_sum_2 = hashlib.sha256(check_sum_1.digest())
        check_sum = check_sum_2.hexdigest()[:8]

        bit_25_address = double_hash + check_sum
        final_address = base58.b58encode(codecs.decode(bit_25_address, 'hex'))
        return final_address.decode()

    def run(self):
        try:
            self.loop = asyncio.get_event_loop()
            self.client, self.server = self.loop.run_until_complete(self.open_connection(self.loop))
            self.loop.run_until_complete(self.start_connection(self.server, self.client))
        except ServerClosingException as e:
            print("Server just closed")
        finally:
            self.loop.close()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Fun Fun Bitcoin')
    parser.add_argument('-p', '--port', dest='port', help='Define the port name')
    args = parser.parse_args()

    # Getting the configureation
    CURVE = ec.SECP256K1()
    SIGNATURE_ALGORITHM = ec.ECDSA(hashes.SHA256())
    START_REWARD = 50
    DECREASE_REWARD = 10

    client = BlockChainClient(args.port, CURVE, SIGNATURE_ALGORITHM, START_REWARD, DECREASE_REWARD)
    print(f"Running on Address: {client.address}")
    client.run()
