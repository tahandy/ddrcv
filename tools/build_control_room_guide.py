"""Build the selected Control Room guide after a first-time-operator read-through.

Reuses the reviewed layout/export engine; preserves the three style-comparison
decks. See doc/slides/control_room/README.md.
"""
from pathlib import Path
import argparse
import json

from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import build_operator_variants as base


ADDITIONS = [
    '''FIRST-TIME QUESTIONS: Where do I get the files? Ask the event organizer for
the tested DDRCV ZIP and, if available, a prepared settings file. A game capture device
brings the machine's video into the computer; selecting a webcam is not a substitute.
A clean recording can be used without live hardware. Renderer files, OBS scenes and
Discord are optional; skip slides 4 and 6 if they are not part of the event.
Double-click the named .bat/.vbs files in File Explorer. Setup option 1 downloads local
Python; no command prompt or prior Python install is needed. On failure keep the setup
window/error and see doc/installation.md before proceeding. Setup does not fetch the
separate ddr_score_render repository. Do not assume this deck installs that program.''',
    '''FIRST-TIME QUESTIONS: A profile is a saved .json settings file. Open… loads a
supplied profile into the form; it does not start capture. Check paths and camera index
for this computer. Without a profile, fill the visible source and mode fields.
Use Capture camera for the game's capture device. Scan lists the devices; choosing one
sets Camera index. Use RTSP only when the organizer supplies a network-stream URL.
For a full 16:9 recording at another resolution, check Resize full 16:9 file to 720p.
Do not choose Still image diagnostics for a full rehearsal. Select the score displayed
by the game: EX for event EX scoring, Money for ordinary scoring toward 1,000,000.
Ask the organizer if uncertain. Leave Publisher address/port at their defaults for a
single-computer setup. Do not run another desktop/workbench/CLI recognition session
against the same port or results storage. The browser workbench is a separate rehearsal
tool; it is not needed for this desktop walkthrough.''',
    '''FIRST-TIME QUESTIONS: The song splash is the title screen immediately before
gameplay. Start there or earlier so DDRCV can see the active players. Click View stream
first; the button then becomes Refresh frame. Each click fetches one still picture.
Check that capture age stays recent, then compare Accepted score during gameplay with
the machine. Last accepted read reports how old that accepted number is. Scores may be
blank before a valid gameplay read and stop updating after gameplay; this is not itself
a fault. Screenshots in this deck show a stopped example, not the expected Running state.
Use the actual event's final score, not a UI screenshot from this guide, for verification.''',
    '''FIRST-TIME QUESTIONS AND CLICK ORDER: Configure between songs. Click Stop in
DDRCV. In Renderer, Browse… to the organizer's ddr_score_render folder, containing
apps/tbd5.py. In OBS, first open the event's scene collection and enable the WebSocket
server through OBS's Tools menu; the WebSocket settings label varies by version.
Copy its port and password. In DDRCV's OBS tab, enter those values and use localhost
when OBS runs on this same computer. For another computer use the organizer's host.
Edit State → scene mapping: the left side names a game screen, the right side names
an existing OBS scene. For example, song_playing maps to Gameplay if that scene exists.
Keep the JSON quotes/commas. The supplied default map may refer to Gameplay and Commentator;
rename those values to your existing scenes or use an organizer-prepared profile.
After entering the renderer and OBS settings, click Apply configuration, then Start.
Only now use Launch renderer, Connect, Check scenes, and Enable automation as applicable.
If auto-launch/connect was selected, those actions may already have happened. Confirm the
actual renderer window and OBS scene. Add the renderer window to the intended OBS scene
using the event's window-capture setup. Default automatic scene-on-Start should remain
off during first rehearsal. Switch scene & pause automation gives manual control;
Enable automation resumes. Pause DDRCV automation before switching directly inside OBS.
Official OBS reference: https://obsproject.com/kb/remote-control-guide
Local references: doc/operator_walkthrough.md §§5–6; ddrcv/apps/tournament_integrations.py.''',
    '''FIRST-TIME QUESTIONS: All three modes retain a results screenshot. P1/P2 mean
Player 1 and Player 2 when names are not read. Capture results must be checked even
for screenshot-only operation. Choose Screenshot folder with Browse…; the default is
screenshots inside the DDRCV folder. Click Apply results settings after choosing the
folder/capture options. Screenshots only and Read names on results apply immediately;
they do not require the top-level Apply and Restart button. These controls affect the
results screen, not the live gameplay scores. Live name display has the independent
Read names on login/song splash checkbox on Status & configuration.
For local-only results leave Publish results to Discord off and skip slide 6. After a
song ends, inspect the selected folder and expand Recent results & recovery. Saved
means retained locally; Sent means delivered to Discord. With Screenshots only enabled,
wait until the results screen ends or its ten-second deadline. Missed detection requires
the event's recording/manual-results procedure, not another retry button.''',
    '''FIRST-TIME QUESTIONS: A Discord webhook is a channel-specific URL that lets
DDRCV post messages. Obtain it from the channel administrator, not from the channel's
ordinary web address. An administrator can create it in Discord Server Settings →
Integrations → Create Webhook, select the results channel, and copy its Webhook URL.
Paste it unchanged into DDRCV's Results tab. Test Discord Webhook sends a real message
even while capture/publishing is off. Check the actual channel. The test does not enable
automatic publishing: separately check Publish results to Discord and click Apply
results settings. This also enables Capture results. Complete one song and check both
the saved screenshot and the real Discord post. No webhook is needed for local files.
Expand Recent results & recovery on the Results tab. Queued, Sending, and Retrying are
actual in-progress labels, not a separate Pending state. Failed records offer Retry
delivery; read the displayed error and fix the connection/webhook before retrying.
Sent records link to the message. More recovery options contains Republish, which
intentionally creates another post. Retry name update edits the existing post when a
name enrichment failed. Sending/retrying requires running capture with results capture
and Discord publishing enabled and a configured webhook. Inspect screenshots before sending.
Official Discord reference: https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks''',
    '''FIRST-TIME QUESTIONS: After the rehearsal settings work, click Save as… and
save tournament.json in the DDRCV folder, or choose another location you will remember.
This creates the event profile. Use Save to update that same file later; Open… loads
it on another launch. Saving records the form, including any edits not yet applied.
If changes should affect the current run, use the correct Apply control separately.
Stop leaves the desktop app open for later Start. Window close leaves recognition
running; launch_desktop.vbs or the DDRCV icon near the Windows clock reopens the panel.
Exit application… is the bottom-panel action that stops the whole app after confirmation.
OBS itself stays open. If Start is disabled because the app is already Running, verify
that existing session instead of trying to launch another driver.''',
    '''FIRST-TIME QUESTIONS: Rehearse after setup or material changes, not only once
for the lifetime of the installation. Check both single- and two-player operation and
the machine's final full-combo score. For every event session, open the saved .json
profile using Open…, verify this machine's device and score mode, and start before
the pre-song title screen. Use the automatic renderer/OBS options saved in the profile,
or launch/connect manually as described on slide 4. Discord checks only apply if used.
If Running is already shown, check that session; do not start a competing instance.
Finish by saving the tested settings with Save/Save as… (slide 7).''',
    '''FIRST-TIME QUESTIONS: Read details & recent errors is an expandable section
on Status & configuration. Its Reset P1 tracking and Reset P2 tracking buttons affect
only the selected live score; they cannot edit a screenshot or saved result. Device
ownership means another application may already be using the capture device. Close
that competing capture or use the event's planned feed-sharing arrangement.
If capture will not start after Stop, wait for the device to release and read the error.
If the source or scores still fail, retain the recording, source details, score mode and
error text for the organizer. For a detailed diagnostic export, stop this session and
use doc/tournament_handoff.md's workbench instructions; do not run both on the same port.
Do not treat a stale displayed score as a newly accepted read. Do not infer a result from
unreadable text; use Screenshots only and the event's manual evidence process.''',
    '''FIRST-TIME QUESTIONS: Outbox means the application's saved original result
images and Discord delivery history, not just the screenshot copies. Defaults are
screenshots and .workbench/results inside the DDRCV folder; a profile may override them.
In File Explorer open the DDRCV folder and browse those folders, or use the full path
chosen in Screenshot folder. Keep both when preserving event evidence. A copied PNG
alone cannot resume queued delivery. Inspect unresolved deliveries before exiting; the
durable records can be retried after the next Start with publishing enabled.
The walkthrough and quick reference are in the DDRCV folder's doc directory. Record
the actual settings in the walkthrough's event setup table, including a technical
contact and recording/manual-results procedure. Profiles contain real credentials;
give them only to authorized operators. Copying a profile does not install Python or
fix machine-specific camera indices and paths on another computer.''',
]


class FinalControlRoom(base.Deck):
    def replace(self, s, old, new, **changes):
        hits=[e for e in s['elements'] if e.get('value')==old]
        assert len(hits)==1,(s['index'],old)
        e=hits[0];s['elements'].remove(e)
        kwargs={k:e[k] for k in ['x','y','w','size','color','font','role']}
        kwargs.update(changes)
        self.txt(s,new,**kwargs)
        if s['title']==old:s['title']=new

    def clear_body(self,s):
        s['elements']=[e for e in s['elements'] if e['x']<.78 or e['y']<self.top or e['y']>=7.07]

    def content(self):
        super().content()
        x,w,y=self.x,self.w,self.top;t=self.t
        s=self.slides[0]
        self.replace(s,'A Windows guide from first setup to event handoff.',
            'Ask the event organizer for the DDRCV ZIP and a game feed or clean recording.')
        self.replace(s,'1280 × 720','Full game screen')
        self.replace(s,'Renderer / OBS • screenshots / Discord','Score display • files • optional Discord')
        self.replace(s,'64-bit Windows\nFirst-install internet\nFull, clean game feed',
            '64-bit Windows\nInternet for setup\nGame capture or recording',size=20)
        self.replace(s,'Optional: event profile,\nrenderer, OBS, webhook.',
            'No display or Discord?\nSkip steps 4 and 6.',size=18)
        self.replace(s,r'Put DDRCV in a writable folder, e.g. C:\Games\ddrcv.',
            r'Extract the ZIP, e.g. to C:\Games\ddrcv.')
        self.replace(s,'setup_desktop.bat → option 1 (local Python).',
            'Double-click setup_desktop.bat; choose 1.',size=17)
        self.replace(s,'launch_desktop.vbs → the panel opens stopped.',
            'Double-click launch_desktop.vbs.',size=17)
        self.replace(s,'No Python install needed beforehand. Wait for success before launching.',
            'No Python needed beforehand. If setup fails, keep the error; see doc/installation.md.',size=15)

        s=self.slides[1]
        self.replace(s,'Status & configuration → Source and Score mode',
            'Status & configuration: Open… loads a supplied .json settings file; otherwise choose Source.')
        self.replace(s,'Scan → select device.\nVerify Camera index.',
            'Game capture device:\nScan → select its camera index.',size=18)
        self.replace(s,'Enter Stream URL.\nFeed must be 1280 × 720.',
            'Only if given a network URL.\nPaste into Stream URL.',size=18)
        self.replace(s,'Browse to a recording.\nResize only full 16:9 files.',
            'Browse to full 16:9 footage.\nIf needed, tick Resize… to 720p.',size=18)
        self.replace(s,'Event EX scoring.\nDesktop default.','EX event scoring.\nAsk organizer if unsure.')
        self.replace(s,'Score toward 1,000,000.\nWorkbench default.','Ordinary score to 1,000,000.\nChoose Money score.')
        self.replace(s,'No borders, cropping, overlays, or stretching. Check mode on every profile.',
            'Live feed: full 1280 × 720, without overlays. Leave Publisher settings at defaults.')

        s=self.slides[2]
        self.replace(s,'Click Start → Running. Begin before the song splash for player presence.',
            'Click Start before the song splash—the title screen just before gameplay.')
        self.replace(s,'Refresh frame for a new picture.\nCheck capture age.',
            'View stream → Refresh frame.\nCheck the picture and its age.')
        self.replace(s,'Splash → gameplay → results.\nConfirmed state should follow.',
            'Running + Capture healthy.\nConfirmed state follows the game.')
        self.replace(s,'Compare with the machine.\nCheck last-read age.',
            'During gameplay, compare\nAccepted score with the machine.')
        self.replace(s,'The picture is fresh and final scores agree, including a full-combo ending.',
            'Blank scores before gameplay are normal. Verify the final score during rehearsal.')
        self.replace(s,'PASS WHEN','EXPECTED')

        s=self.slides[3]
        self.replace(s,'Connect the display and OBS scene control','Optional: add a score display and OBS')
        self.replace(s,'Apply edited paths and connection settings before using their buttons.',
            'Skip this step if you only need DDRCV scores or local screenshots.')
        self.clear_body(s)
        self.box(s,x,y,w,.52,t['tint'])
        self.txt(s,'Stop → enter settings in the tabs → Apply configuration → Start',x+.15,y+.12,w-.3,20,t['accent'],'UIB')
        cw=(w-.54)/2;rx=x+cw+.54
        self.heading(s,'Score display · Renderer tab',x,y+.8,cw,21)
        self.heading(s,'Scene switching · OBS tab',rx,y+.8,cw,21)
        left=[('Get the display files','Ask organizer for ddr_score_render.\nBrowse… to that folder in Renderer.'),
              ('Launch after Start','Click Launch renderer. Compare\nits scores with the machine.'),
              ('Show the window in OBS','Add a Window Capture source in OBS;\nchoose the renderer window.')]
        right=[('Enable control in OBS','Tools → WebSocket settings.\nCopy its port and password.'),
               ('Enter connection + scene map','Same PC: localhost + OBS port/password.\nMap game screens to existing scenes.'),
               ('Apply → Start → Connect','Check scenes → Enable automation.\nVerify the actual OBS scene changes.')]
        for xx,items in [(x,left),(rx,right)]:
            for i,(a,b) in enumerate(items):self.step(s,i+1,a,b,xx,y+1.35+i*1.02,cw,19)
        self.note(s,'MANUAL OBS','Switch scene & pause automation takes control; Enable automation resumes.')

        s=self.slides[4]
        self.replace(s,'Choose the results evidence you need','Choose what to save from the results screen')
        self.replace(s,'Results → Capture results ON → choose a writable Screenshot folder',
            'Results: tick Capture results, choose Screenshot folder, then Apply results settings.')
        self.replace(s,'READ NAMES','READ NAMES\nON RESULTS',size=10,y=y+.06)
        self.replace(s,'Scores first; names can update later.',
            'Screenshot + scores; names can update later.',size=17)
        self.replace(s,'Keep scores without player-name parsing.',
            'Screenshot + scores; P1/P2 mean Player 1/2.',size=17)
        self.replace(s,'Save on results departure or after 10 seconds.',
            'Screenshot, no text. Save when results end or after 10s.',size=17)
        self.replace(s,'Apply results settings','Local screenshots only?',font='UIB')
        self.replace(s,'Applies Results controls without resetting gameplay scores.',
            'Leave Publish results to Discord off. Files still save; skip step 6.',size=18)
        self.replace(s,'Screenshots only and Read names on results apply as you toggle them.',
            'Screenshots only and Read names on results change results parsing, not gameplay scores.',size=18)

        s=self.slides[5]
        self.replace(s,'Verify the destination, then publish','Optional: send results to Discord')
        self.replace(s,'Results → Webhook URL. A webhook test sends a real message.',
            'A webhook is a channel’s posting link. Ask its administrator for the Webhook URL.')
        # Keep the actual input screenshot; rebuild the steps and recovery rows below.
        s['elements']=[e for e in s['elements'] if e['x']<.78 or e['y']<3.15 or e['y']>=7.07]
        lw=w*.55;rx=x+lw+.35;rw=w-lw-.35;cy=3.17
        for i,(a,b) in enumerate([
            ('Paste the URL in Results','Test Discord Webhook sends a real\nmessage. Verify the channel.'),
            ('Enable automatic posts','Publish results to Discord →\nApply results settings.'),
            ('Verify one full result','Finish a song. Inspect its screenshot\nand the actual Discord post.')]):
            self.step(s,i+1,a,b,x,cy+i*.99,lw,19)
        self.heading(s,'Expand Recent results & recovery',rx,cy,rw,18)
        rows=['Saved → Send saved result','Queued / Sending / Retrying → wait.',
              'Failed → fix error, then Retry delivery','Sent → Open Discord message',
              'More recovery options → Republish\nCreates another post.']
        for i,line in enumerate(rows):
            yy=cy+.55+i*.47
            self.txt(s,line,rx,yy,rw,16)
            if i<4:self.rule(s,rx,yy+.39,rw)
        self.note(s,'SEND / RETRY','Needs running capture, Capture results, Discord publishing, and a webhook.')

        s=self.slides[6]
        self.replace(s,'Know what applies, resets, or keeps running','Save your setup and use the right controls')
        self.replace(s,'The form, running session, and saved profile can contain different settings.',
            'A profile is a settings file. Save as… → tournament.json in DDRCV; Open… loads it.')
        self.replace(s,'Stop capture. Exit also closes the backend; OBS stays open.',
            'Stop ends capture; Exit closes the whole app. OBS stays open.')
        self.replace(s,'Capture continues. Reopen from the tray or launcher.',
            'Capture continues. Double-click launch_desktop.vbs to reopen.')

        s=self.slides[7]
        self.replace(s,'Rehearse once; repeat the startup checks','Rehearse your setup; check every session')
        self.replace(s,'Source/index, EX/Money, and integrations.',
            'Correct device, EX/Money, and any optional connections.')
        self.replace(s,'Verify screenshot files and the actual Discord post.',
            'Check the Screenshot folder and Discord post, if used.')
        self.replace(s,'Check capture freshness, accepted scores, display, and scenes.',
            'If already Running, check that session. Otherwise click Start.')
        self.replace(s,'Another operator can start the station and recover a saved result unaided.',
            'Save the tested setup (step 7). Verify scores, display, and scenes before the event.')

        s=self.slides[8]
        self.replace(s,'Read details & recent errors explains rejected reads and recent failures.',
            'Status & configuration → expand Read details & recent errors. Reset buttons are there.')
        self.replace(s,'Check cable, index/URL, 720p, and capture-device ownership.',
            'Check cable/device, 720p, and whether another app uses the camera.',size=17)
        self.replace(s,'Reset P1/P2 tracking clears that live score. Saved results stay.',
            'Reset P1/P2 tracking clears that live score; saved results stay.',size=17)
        self.replace(s,'Stop the other app/workbench/CLI; it may still be running.',
            'Stop the other DDRCV session. Closing its window is not enough.',size=17)

        s=self.slides[9]
        self.replace(s,'Leave a usable profile and an evidence trail','Hand over the profile and keep the evidence')
        self.replace(s,'Fill the event setup table in the written walkthrough before handing over.',
            'Record these details in doc/operator_walkthrough.md, inside the DDRCV folder.')
        self.replace(s,'Keep screenshots and the Results outbox.',
            'Keep screenshot copies and the saved originals/history.')
        self.replace(s,'EVIDENCE','IN DDRCV FOLDER',size=10)
        self.replace(s,'screenshots/  +  .workbench/results/  (defaults)',
            'screenshots/ = copies; .workbench/results/ = originals + delivery history',size=16)
        for i,s in enumerate(self.slides):
            s['notes']=ADDITIONS[i]+'\n\nADDITIONAL REFERENCE\n'+s['notes']
            s['copy']=[e['value'] for e in s['elements'] if e.get('role')=='content']
        return self.slides


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--font-dir',type=Path,default=Path('C:/Windows/Fonts'))
    args=parser.parse_args()
    for name,file in [('UI','segoeui.ttf'),('UIB','segoeuib.ttf'),('MonoB','consolab.ttf'),('Serif','georgia.ttf')]:
        pdfmetrics.registerFont(TTFont(name,str(args.font_dir/file)))
    base.OUT=base.ROOT/'doc/slides'
    theme={**base.THEMES[1],'id':'control_room'}
    report=base.render(FinalControlRoom(theme))
    out=base.OUT/theme['id']
    sheet=Image.new('RGB',(1200,1830),'#DDE3E9')
    draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype(str(args.font_dir/'segoeui.ttf'),19)
    for i in range(10):
        im=Image.open(out/'preview'/f'{i+1:02d}.png');im.thumbnail((592,333))
        x=(i%2)*600;y=(i//2)*366;sheet.paste(im,(x+4,y))
        draw.text((x+14,y+337),f'{i+1:02d}',font=font,fill='#24374B')
    sheet.save(out/'contact_sheet.png')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
