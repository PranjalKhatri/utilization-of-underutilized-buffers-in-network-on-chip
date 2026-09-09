from gem5.resources.client import get_resource_json_obj
import pprint

resource = get_resource_json_obj(
    "x86-parsec",
    resource_version="1.0.0",
)

pprint.pp(resource)
