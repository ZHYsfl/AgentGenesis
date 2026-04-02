"""
Microservice Avalanche - Transaction Generator

Generates 10 transactions with random items, quantities, and prices.
"""

import random
from typing import Optional


ITEMS = [
    "laptop", "phone", "tablet", "watch", "headphones",
    "keyboard", "mouse", "monitor", "camera", "speaker",
    "book", "game", "toy", "shoes", "shirt",
    "bag", "wallet", "belt", "glasses", "pen"
]


def generate_transactions(count: int = 10, seed: Optional[int] = None) -> list[dict]:
    """
    Generate random transactions.

    Each transaction:
    - tx_id: Unique ID (tx_0, tx_1, ...)
    - item: Random item name
    - quantity: 1-5
    - price: 10.0-1000.0
    """
    if seed is not None:
        random.seed(seed)

    transactions = []
    for i in range(count):
        tx = {
            "tx_id": f"tx_{i}",
            "item": random.choice(ITEMS),
            "quantity": random.randint(1, 5),
            "price": round(random.uniform(10.0, 1000.0), 2)
        }
        transactions.append(tx)

    return transactions


if __name__ == "__main__":
    txs = generate_transactions(10, seed=42)
    for tx in txs:
        print(f"{tx['tx_id']}: {tx['quantity']}x {tx['item']} @ ${tx['price']}")
