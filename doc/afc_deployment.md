## Context 

DDRCV was deployed during Arrows for Charity VI only to parse the raw EX score and take screenshots. Prior to
the tournament it had only had a ~3 hour test run in a real scenario connected to the machine, on the Wednesday 
before the tournament. A number of minor robustness issues were identified, and I decided to disable the song lookup
feature (used to generate EX percentage) for the tournament. Additionally, internet connection sharing decided to put
up a fight in the small window we had to set up everything that morning, so publishing results screenshots to Discord
was also disabled (although screenshot generation was still enabled).

# Retrospective

- The delay of 5 seconds before taking the screenshot may be a little long if event+EX mode is enabled. The score 
increase animation is shorter for EX. More importantly, players would hit the button before a screenshot could be taken.
- We occasionally take two screenshots. This would indicate that we lose the results screen momentarily. If I had to
guess, I think the slightly dark background that scrolls under "RESULTS" may be enough to throw off the hash just a bit
as it moves. May be able to alleviate this just by upping the hash threshold by a couple; a more robust solution would
be to convert the target and chip to black/white by thresholding on the HSV saturation.
- There are a few instances where transitions are triggered incorrectly. Luckily, none were seen during gameplay. I 
think most of them are as it transitions _to_ the song select screen after a restart. Not sure why this would be happening,
needs investigating. The current `song_select` state targets are grabbed from YouTube videos, we should just grab new ones.
- I did also notice that it got stuck once on the gameplay overlay -- we may want the OBS controller to not just check for 
a state transition, but also current state and active scene (e.g. not song_playing state && scene == Gameplay, switch to Baseline).
- I switched to color similarity for difficulty determination on the song splash screen the night before AFC, but a variety
of factors made me decide not to use it day-of. Needs testing.
- It seems like we jump the gun on the scene transition from song splash to gameplay. I don't think we lose the state,
but I can't be 100% certain at the moment. I was originally wanting to chalk it up to latency on the streaming computer,
but I think we'd see a bigger discrepancy during gameplay; I now don't think it's this.
- Many of these kind of intermittent problems may be solved by making sure we have the same state for a number of frames
before taking any actions, however this may lead to latency if it's just plugged in wholesale to everything in `driver`.
Be careful.
- The OBS controller has a manual override mode, which disables control via state change. However, commentators didn't
really understand how to click the button. They would pull up Twitch chat over the controller website and wouldn't see it,
and as a result would click on the commentator scene in OBS, and then the controller would change it back. So, there needs to 
be some UX updates there, as well as making sure that they understand how to make it bend to their will. Unfortunately,
they need to _disable_ the override to get things automated again, and there's a non-zero chance they forget to do that.
Possibly put it on a timer and/or integrate with streamdeck.
- I'd like to look into using quantized Mobilenet for the jacket database. Currently, effnet-B0 takes ~200 ms to run
on the Pi 5, which is _fine_, but it worries me a little bit if there's any latency. I don't have any evidence of any
problems, but this could theoretically impact the identification of the gameplay state, which is 100% the most important
thing to identify.
- I was worried about the Pi keeping up without dropping frames, particularly with respect to the gutter identification
during gameplay (required to _stop_ updating the score because of that stupid ass rocket). Seems fine, no problems.
- On the score rendering side: The number-go-up animation seems to be triggered once the machine registers the note grade.
Consider the case where the players have equivalent EX score. On the next step, both players hit a Marvelous, but Player1
hits it on the early side of the timing window. I'm not immersed in the minutiae of the timing windows, but assume that
there's effectively 2-3 frames that may occur in the Marv window, depending on the internal ticks. Player1's animation then 
starts a couple frames ahead of Player2's. As a result, when the scores are parsed and sent to the renderer, this can
induce the flickering effect even when there is no effective EX score difference between the players. I think smoothing
out this behavior needs to be handled by whatever is rendering the scores and not `driver`. But, that's the cause.