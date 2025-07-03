import json
from django import template

register = template.Library()

@register.filter
def pretty_json(value):
    try:
        return json.dumps(value, indent=2)
    except:
        return value
