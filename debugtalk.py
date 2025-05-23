import json

def get_url_from_response(response):
    """修改返回body"""
    data: dict = response.resp_obj.json()
    return data["url"]