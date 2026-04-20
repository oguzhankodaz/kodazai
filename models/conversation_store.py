conversations = {}


def get_conversation(cid):
    return conversations.get(cid)


def save_conversation(cid, data):
    conversations[cid] = data


def clear_conversation(cid):
    conversations.pop(cid, None)