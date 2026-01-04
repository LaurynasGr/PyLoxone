import json
from base64 import b64encode
import logging
from urllib.parse import quote

import websockets as wslib
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from Crypto.Util import Padding

_LOGGER = logging.getLogger(__name__)

def normalize_public_key(public_key: str) -> str:
  """
  Normalize the public key into a valid PEM block.
  The websocket returns the key as a single-line string without newlines.
  """

  header = "-----BEGIN PUBLIC KEY-----"
  footer = "-----END PUBLIC KEY-----"

  return public_key.replace(header, f"{header}\n").replace(footer, f"\n{footer}").strip()

def get_auth_payload(
  public_key: str,
  session_token: str,
  token: str,
  active_user: str,
) -> str:
  """
  - generate random AES key/iv
  - encrypt JWT token with AES-CBC/PKCS7
  - RSA encrypt "aesKey:iv:sessionToken" with the provided public key
  - send the authenticate command over the websocket
  """

  pem_public_key = normalize_public_key(public_key)
  aes_key_bytes = get_random_bytes(16).hex().encode("utf-8")
  iv = get_random_bytes(16)

  rsa_payload = f"{aes_key_bytes.hex()}:{iv.hex()}:{session_token}".encode("utf-8")
  rsa_key = RSA.import_key(pem_public_key)
  rsa_cipher = PKCS1_v1_5.new(rsa_key)
  rsa_encrypted = b64encode(rsa_cipher.encrypt(rsa_payload)).decode("ascii")

  cipher = AES.new(aes_key_bytes, AES.MODE_CBC, iv)
  padded = Padding.pad(token.encode("utf-8"), AES.block_size)
  ciphertext_b64 = b64encode(cipher.encrypt(padded)).decode("ascii")

  return (
    f"secure/authenticate/"
    f"{quote(active_user, safe="")}/"
    f"{quote(rsa_encrypted, safe="")}/"
    f"{quote(ciphertext_b64, safe="")}"
  )

async def getkey(connection: wslib.ClientConnection):
  await connection.send("audio/cfg/getkey/full")

async def authenticate_with_audio_server(connection: wslib.ClientConnection, token: str, active_user: str):
  session_token: str | None = None
  auth_result: str | None = None
  async for message in connection:
    # print(f"Received message: {message}\n----------------------------")
    if message.startswith("LWSS"):
      # Example: LWSS V 16.1.11.06 | ~API:1.6~ | Session-Token: <token>
      if "Session-Token:" in message:
        session_token = message.split("Session-Token:")[1].strip()
      _LOGGER.info(f"Received Hello message... Sending getkey command...")
      await getkey(connection)
      continue

    json_message = json.loads(message)
    if isinstance(json_message, dict):
      if json_message.get("getkey_result"):
        _LOGGER.info(f"Received getkey response....")
        if not session_token:
          error_message = "No session token captured; cannot authenticate."
          _LOGGER.error(error_message)
          raise Exception(error_message)

        payload = get_auth_payload(
          json_message.get("getkey_result")[0].get("pubkey"),
          session_token,
          token,
          active_user,
        )
        await connection.send(payload)
        continue
      elif json_message.get("authenticate_result"):
        auth_result = json_message.get("authenticate_result")
        _LOGGER.info(f"Received Authenticate result: {auth_result}")
        if auth_result == "authentication successful":
          return True

      # If we get here an unexpected message was received before auth was completed.
      # Exit and let PyLoxone fallback to the simpler (old) mediaplayer implementation.
      error_message = f"Audio server error: {auth_result or 'unknown error'}"
      _LOGGER.error(error_message)
      raise Exception(error_message)

if __name__ == "__main__":
  print("Starting audioserver test...")