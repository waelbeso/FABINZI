from pathlib import Path

path = Path('mobile/customer_app/lib/core/api_client.dart')
text = path.read_text()
old = """  Future<SessionTokens> _refreshTokens() {
    final active = _refreshing;
    if (active != null) return active;
    final next = _performRefresh();
    _refreshing = next;
    next.whenComplete(() {
      if (identical(_refreshing, next)) _refreshing = null;
    });
    return next;
  }
"""
new = """  Future<SessionTokens> _refreshTokens() async {
    final active = _refreshing;
    if (active != null) return active;
    final next = _performRefresh();
    _refreshing = next;
    try {
      return await next;
    } finally {
      if (identical(_refreshing, next)) _refreshing = null;
    }
  }
"""
if old not in text:
    if new in text:
        raise SystemExit('Refresh lifecycle fix is already present.')
    raise SystemExit('Expected refresh lifecycle block not found.')
path.write_text(text.replace(old, new, 1))
