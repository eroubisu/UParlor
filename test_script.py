import sys
sys.path.insert(0, 'Server')

from server.lobby.command_registry import find_global_handler, _GLOBAL_HANDLERS
print('Registered global handlers:', list(_GLOBAL_HANDLERS.keys()))

handler = find_global_handler('/create')
print('find_global_handler(\"/create\"):', handler)

from server.lobby.engine import LobbyEngine
lobby = LobbyEngine.__new__(LobbyEngine)
import threading
lobby._lock = threading.Lock()
lobby._engines = {}
lobby._player_locations = {}
lobby.pending_confirms = {}
lobby._help_viewers = set()

player_data = {'name': 'testplayer', 'uno': {}}

result = lobby.process_command(player_data, '/create uno {}')
print('Result:', result)
print('Type:', type(result))
