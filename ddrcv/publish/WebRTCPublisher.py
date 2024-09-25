import asyncio
import json
from multiprocessing import Process, Lock, Manager
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
import websockets


def parse_ice_candidate(candidate_str):
    fields = candidate_str.split()
    return {
        "foundation": fields[0].split(":")[1],
        "component": int(fields[1]),
        "protocol": fields[2].lower(),
        "priority": int(fields[3]),
        "ip": fields[4],
        "port": int(fields[5]),
        "type": fields[7],
        "relatedAddress": fields[9] if "raddr" in fields else None,
        "relatedPort": int(fields[11]) if "rport" in fields else None,
        "tcpType": fields[13] if "tcptype" in fields else None
    }


class Publisher:
    def __init__(self, host='127.0.0.1', port=9000):
        self.host = host
        self.port = port
        manager = Manager()
        self.latest_message = manager.dict()
        self.lock = Lock()
        self.peer_connections = {}

    def start(self):
        self.process = Process(target=self._run_in_process, args=(self.latest_message, self.lock))
        self.process.start()

    def send_message(self, json_contents):
        with self.lock:
            self.latest_message.clear()
            self.latest_message.update(json_contents)

    def stop(self):
        self.send_message(None)
        self.process.join()

    def _run_in_process(self, latest_message, lock):
        asyncio.run(self._run_webrtc_and_signaling(latest_message, lock))

    def _create_peer_connection(self, websocket):
        pc = RTCPeerConnection()

        @pc.on("iceconnectionstatechange")
        async def on_ice_state_change():
            if pc.iceConnectionState == "closed":
                print(f"ICE connection closed for {websocket.remote_address}. Cleaning up.")
                if websocket in self.peer_connections:
                    del self.peer_connections[websocket]

        return pc

    async def _run_webrtc_and_signaling(self, latest_message, lock):
        async def handle_offer(websocket, path):
            if websocket not in self.peer_connections:
                print(f"Creating new RTCPeerConnection for {websocket.remote_address}.")
                self.peer_connections[websocket] = self._create_peer_connection(websocket)

            pc = self.peer_connections[websocket]

            # Create the data channel **before** generating the SDP offer
            data_channel = pc.createDataChannel('chat')

            @data_channel.on("open")
            def on_open():
                print("Data channel is open for", websocket.remote_address)
                asyncio.create_task(send_messages())

            @data_channel.on("close")
            def on_close():
                print(f"Data channel closed for {websocket.remote_address}")

            async def send_messages():
                while True:
                    with lock:
                        if latest_message:
                            if data_channel.readyState == 'open':
                                message_to_send = json.dumps(dict(latest_message))
                                data_channel.send(message_to_send)
                                print(f"Sent to {websocket.remote_address}: {message_to_send}")
                            else:
                                print("Data channel is not open yet.")
                    await asyncio.sleep(0.5)

            # Handle SDP Offer
            async for message in websocket:
                data = json.loads(message)

                if "sdp" in data:
                    sdp = data["sdp"]
                    offer = RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"])

                    if pc.signalingState == "closed":
                        print(f"PeerConnection for {websocket.remote_address} is closed, creating a new one.")
                        self.peer_connections[websocket] = self._create_peer_connection(websocket)
                        pc = self.peer_connections[websocket]

                    await pc.setRemoteDescription(offer)
                    answer = await pc.createAnswer()

                    sdp_lines = answer.sdp.splitlines()
                    bundle_line = None
                    mid_lines = []
                    filtered_sdp_lines = []
                    for line in sdp_lines:
                        if line.startswith("m=audio") or line.startswith("m=video"):
                            continue
                        if line.startswith("a=mid:"):
                            mid_lines.append(line.split(":")[1].strip())
                        if line.startswith("a=group:BUNDLE"):
                            bundle_line = line
                        filtered_sdp_lines.append(line)

                    if bundle_line and mid_lines:
                        filtered_sdp_lines.append(f"a=group:BUNDLE {' '.join(mid_lines)}")

                    modified_sdp = "\r\n".join(filtered_sdp_lines)
                    await pc.setLocalDescription(RTCSessionDescription(sdp=modified_sdp, type=answer.type))

                    await websocket.send(json.dumps({
                        "sdp": {
                            "sdp": pc.localDescription.sdp,
                            "type": pc.localDescription.type
                        }
                    }))

                if "candidate" in data:
                    candidate = data["candidate"]
                    parsed_candidate = parse_ice_candidate(candidate["candidate"])
                    ice_candidate = RTCIceCandidate(
                        component=parsed_candidate["component"],
                        foundation=parsed_candidate["foundation"],
                        protocol=parsed_candidate["protocol"],
                        priority=parsed_candidate["priority"],
                        ip=parsed_candidate["ip"],
                        port=parsed_candidate["port"],
                        type=parsed_candidate["type"],
                        relatedAddress=parsed_candidate.get("relatedAddress"),
                        relatedPort=parsed_candidate.get("relatedPort"),
                        tcpType=parsed_candidate.get("tcpType"),
                        sdpMid=candidate.get("sdpMid"),
                        sdpMLineIndex=candidate.get("sdpMLineIndex")
                    )

                    await pc.addIceCandidate(ice_candidate)

        # WebSocket server
        async with websockets.serve(handle_offer, self.host, self.port):
            print(f"WebSocket signaling server running on ws://{self.host}:{self.port}")
            await asyncio.Future()  # Run forever


if __name__ == "__main__":
    import random

    # Create a list of messages to send
    data = [
        {"type": "message", "content": "Hello, World!"},
        {"type": "message", "content": "This is WebRTC"},
        {"type": "message", "content": "Message #3"}
    ]

    # Start the Publisher
    pub = Publisher()
    pub.start()

    async def send_periodic_messages():
        while True:
            datum = random.choice(data)
            print(f'Sending message: {datum}')
            pub.send_message(datum)
            await asyncio.sleep(random.randint(3, 9))

    # Run the message sending loop asynchronously
    asyncio.run(send_periodic_messages())

    # Stop the Publisher once done (if needed)
    pub.stop()
