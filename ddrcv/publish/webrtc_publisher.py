import asyncio
import json
from multiprocessing import Process, Lock, Manager
from aiortc import RTCPeerConnection, RTCSessionDescription
import websockets


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
            print(f"ICE connection state for {websocket.remote_address}: {pc.iceConnectionState}")
            if pc.iceConnectionState == "closed":
                print(f"ICE connection closed for {websocket.remote_address}. Cleaning up.")
                if websocket in self.peer_connections:
                    del self.peer_connections[websocket]

        @pc.on("icecandidate")
        async def on_ice_candidate(event):
            if event.candidate:
                candidate_dict = {
                    'candidate': event.candidate.candidate,
                    'sdpMid': event.candidate.sdpMid,
                    'sdpMLineIndex': event.candidate.sdpMLineIndex,
                }
                await websocket.send(json.dumps({'candidate': candidate_dict}))

        return pc

    async def _run_webrtc_and_signaling(self, latest_message, lock):
        async def handle_offer_request(websocket, path):
            if websocket not in self.peer_connections:
                print(f"Creating new RTCPeerConnection for {websocket.remote_address}.")
                self.peer_connections[websocket] = self._create_peer_connection(websocket)

            pc = self.peer_connections[websocket]

            # Create a data channel on the server side before creating an SDP offer
            data_channel = pc.createDataChannel('chat')

            @data_channel.on("open")
            def on_open():
                print(f"Data channel is open with {websocket.remote_address}")
                asyncio.create_task(send_messages(data_channel))

            @data_channel.on("message")
            def on_message(message):
                print(f"Received message from {websocket.remote_address}: {message}")

            @data_channel.on("close")
            def on_close():
                print(f"Data channel closed with {websocket.remote_address}")

            async for message in websocket:
                data = json.loads(message)

                # Client is requesting an SDP offer
                if "request_offer" in data:
                    print("Client requested SDP offer")
                    # Create an SDP offer
                    offer = await pc.createOffer()
                    await pc.setLocalDescription(offer)

                    # Send the SDP offer to the client
                    await websocket.send(json.dumps({
                        "sdp": {
                            "sdp": pc.localDescription.sdp,
                            "type": pc.localDescription.type
                        }
                    }))

                # Handle SDP answer from the client
                elif "sdp" in data:
                    sdp = data["sdp"]
                    answer = RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"])
                    await pc.setRemoteDescription(answer)

                # Handle ICE candidates from the client
                elif "candidate" in data:
                    candidate = data["candidate"]
                    try:
                        await pc.addIceCandidate(candidate)
                    except Exception as e:
                        print(f"Error adding ICE candidate: {e}")

            async def send_messages(channel):
                while True:
                    with lock:
                        if latest_message:
                            if channel.readyState == 'open':
                                message_to_send = json.dumps(dict(latest_message))
                                channel.send(message_to_send)
                                print(f"Sent to {websocket.remote_address}: {message_to_send}")
                            else:
                                print("Data channel is not open yet.")
                    await asyncio.sleep(0.5)

        # WebSocket server
        async with websockets.serve(handle_offer_request, self.host, self.port):
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
