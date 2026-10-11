import requests
from django.http import JsonResponse


def ping(request):
    """Placeholder endpoint to confirm the pron_api app is wired up."""
    return JsonResponse({"app": "pron_api", "status": "ok"})


def uberduck_arpabet(request):
    """Fetch the ARPABET for a word from Uberduck's g2p API and return it to the
    frontend. The word comes from the `text` query param (defaults to "average").
    Uberduck returns e.g. {"arpabet": "{AE1 V ER0 IH0 JH}", "lookups": {...}}."""
    word = (request.GET.get("text") or "average").strip()
    try:
        resp = requests.get(
            "https://api.uberduck.ai/g2p", params={"text": word}, timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return JsonResponse({"word": word, "arpabet": "", "error": str(e)}, status=502)
    return JsonResponse({"word": word, "arpabet": data.get("arpabet", "")})
