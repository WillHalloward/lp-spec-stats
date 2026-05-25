import requests

cookies = {
    'JSESSIONID': 'node01txn8dk939xie1roqnxhyertle5767.node0',
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-GB,en;q=0.9',
    # 'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Content-Type': 'application/json',
    'Origin': 'https://raid-helper.xyz',
    'DNT': '1',
    'Sec-GPC': '1',
    'Connection': 'keep-alive',
    'Referer': 'https://raid-helper.xyz/calendar/1411835313696804976',
    # 'Cookie': 'JSESSIONID=node01txn8dk939xie1roqnxhyertle5767.node0',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'Priority': 'u=0',
}

json_data = {
    'serverid': '1411835313696804976',
    'accessToken': 'DQnBnZFQOz-RC-CTdHzVDxWspW4SUQ7t8ogv2n4TX8GpBcYU2GMOT6o6GKtZpm8I82llH7GquyvS2m8uOSLYcFi3oBZ-2Ji1Sz0M83XtaFMzxTc',
}

response = requests.post('https://raid-helper.xyz/api/events/', cookies=cookies, headers=headers, json=json_data)
print(response.text)
# Note: json_data will not be serialized by requests
# exactly as it was in the original request.
#data = '{"serverid":"1411835313696804976","accessToken":"DQnBnZFQOz-RC-CTdHzVDxWspW4SUQ7t8ogv2n4TX8GpBcYU2GMOT6o6GKtZpm8I82llH7GquyvS2m8uOSLYcFi3oBZ-2Ji1Sz0M83XtaFMzxTc"}'
#response = requests.post('https://raid-helper.xyz/api/events/', cookies=cookies, headers=headers, data=data)
