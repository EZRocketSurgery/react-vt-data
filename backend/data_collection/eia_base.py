import requests
import pandas
import os
import logging

logger = logging.getLogger(__name__)
EIA_API_KEY = os.getenv("EIA_API_KEY")
BASE_URL = "https://api.eia.gov/v2/"

def get_data_keys(endpoint :str) -> list:
    """
    Retrieves the data keys for a given EIA API endpoint.

    Args:
        endpoint (str): The EIA API endpoint to query.

    Returns:
        list: A list containing the data keys.
    """
    meta = requests.get(BASE_URL + endpoint, params={"api_key": EIA_API_KEY}).json()
    keys = list(meta["response"]["data"].keys())
    return keys

def get_endpoints(json: dict) -> list|None:
    """
    Retrieves the endpoint IDs from the EIA API response JSON.

    Args:
        json (dict): The JSON response from the EIA API.

    Returns:
        list|None: A list containing the endpoint IDs, or None if no routes are found.
    If no routes are found, it's a data endpoint and there are no further routes to retrieve.
    """
    routes = json["response"]["routes"]
    if not routes:
        return None
    endpoints = []
    for key in routes:
        endpoints.append(key['id'])
    return endpoints

