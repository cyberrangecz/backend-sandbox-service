import gitlab


def get_file_from_repo(token):
    gl = gitlab.Gitlab('http://10.0.0.1', private_token=token)
