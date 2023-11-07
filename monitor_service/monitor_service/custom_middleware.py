from django.shortcuts import redirect

class RedirectLoggedInMiddleware:
    def __init__(self, get_response):
      self.get_response = get_response

    def __call__(self, request):
      if (request.user.is_authenticated):
        if ("/sigfox_messages/accounts/login" in request.path):
          return redirect("/sigfox_messages/")
      elif (("/sigfox_messages/uplink" not in request.path) and
            ("/sigfox_messages/downlink" not in request.path) and
            ("/sigfox_messages/accounts/login" not in request.path) and
            ("/sigfox_messages/register" not in request.path) and
            ("/static" not in request.path)):
        # User is not authenticated, redirect him to login page
        return redirect("/sigfox_messages/accounts/login/")

      return self.get_response(request)
