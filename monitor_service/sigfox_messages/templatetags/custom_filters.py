from django import template
from django.template.defaultfilters import stringfilter

register = template.Library()

@register.filter
@stringfilter
def contains(value, arg):
  return (arg in value)

@register.filter
@stringfilter
def differs_from(value, arg):
  return (value != arg)
