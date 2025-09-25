"""Module to hande queue population"""

import asyncio
import json
import logging

from automation_server_client import Workqueue

from helpers import config


def retrieve_items_for_queue() -> list[dict]:
    """Function to populate queue"""
    data = []
    references = []

    items = [
        {"reference": ref, "data": d} for ref, d in zip(references, data, strict=True)
    ]

    return items


def create_sort_key(item: dict) -> str:
    """
    Create a sort key based on the entire JSON structure.
    Converts the item to a sorted JSON string for consistent ordering.
    """
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


async def concurrent_add(
    workqueue: Workqueue, items: list[dict], logger: logging.Logger
) -> None:
    """
    Populate the workqueue with items to be processed.
    Uses concurrency and retries with exponential backoff.

    Args:
        workqueue (Workqueue): The workqueue to populate.
        items (list[dict]): List of items to add to the queue.
        logger (logging.Logger): Logger for logging messages.

    Returns:
        None

    Raises:
        Exception: If adding an item fails after all retries.
    """
    sem = asyncio.Semaphore(config.MAX_CONCURRENCY)

    async def add_one(it: dict):
        reference = str(it.get("reference") or "")
        data = {"item": it}

        async with sem:
            for attempt in range(1, config.MAX_RETRIES + 1):
                try:
                    await asyncio.to_thread(workqueue.add_item, data, reference)
                    logger.info(f"Added item to queue with reference: {reference}")
                    return True

                except Exception as e:
                    if attempt >= config.MAX_RETRIES:
                        logger.error(
                            f"Failed to add item {reference} after {attempt} attempts: {e}"
                        )
                        return False

                    backoff = config.RETRY_BASE_DELAY * (2 ** (attempt - 1))

                    logger.warning(
                        f"Error adding {reference} (attempt {attempt}/{config.MAX_RETRIES}). "
                        f"Retrying in {backoff:.2f}s... {e}"
                    )
                    await asyncio.sleep(backoff)

    if not items:
        logger.info("No new items to add.")
        return

    sorted_items = sorted(items, key=create_sort_key)
    logger.info(
        f"Processing {len(sorted_items)} items sorted by complete JSON structure"
    )

    results = await asyncio.gather(*(add_one(i) for i in sorted_items))
    successes = sum(1 for r in results if r)
    failures = len(results) - successes

    logger.info(
        f"Summary: {successes} succeeded, {failures} failed out of {len(results)}"
    )
