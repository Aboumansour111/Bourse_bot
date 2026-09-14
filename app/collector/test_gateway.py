import requests

GATEWAY_URL = "http://127.0.0.1:18080"


def get_quote(inscode: int):
    url = f"{GATEWAY_URL}/quote/{inscode}"

    response = requests.get(url, timeout=20)
    response.raise_for_status()

    return response.json()


if __name__ == "__main__":
    inscode = 46348559193224090

    data = get_quote(inscode)

    print("Gateway status:", data.get("status"))
    print("Inscode:", data.get("inscode"))
    print("Data received:", data.get("data") is not None)
    print(data)
