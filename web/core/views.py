from django.conf import settings
from django.shortcuts import render_to_response
from django.template import RequestContext

from core.models import *

# INDEX

def index(request):
	data = {}
	return render_to_response('index.html',
						   data,
						   context_instance=RequestContext(request))
	