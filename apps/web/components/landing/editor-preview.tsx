"use client";

import { AudioLines, ChevronDown, Film, FolderOpen, Pause, Play, Scissors, SlidersHorizontal } from "lucide-react";
import Image from "next/image";
import { useState, type CSSProperties } from "react";
import styles from "./landing.module.css";

const LINES = [
  { english: "Stay a little longer.", malayalam: "കുറച്ചു നേരം കൂടി നിൽക്കൂ.", time: "00:01.40", position: "18%" },
  { english: "There's still time.", malayalam: "ഇനിയും സമയമുണ്ട്.", time: "00:04.20", position: "49%" },
  { english: "I'm right here.", malayalam: "ഞാൻ ഇവിടെയുണ്ട്.", time: "00:07.00", position: "81%" },
];

/** An isolated illustration: it never creates a project or invokes a provider. */
export function EditorPreview({ playing, onToggle }: { playing: boolean; onToggle: () => void }) {
  const [selection, setSelection] = useState(1);
  const line = LINES[selection];
  return <div className={styles.editorMock} role="group" aria-label="Illustrative editor preview">
    <div className={styles.mockTopbar}>
      <span className={styles.mockBrand}><Film size={13} /> CineDub <i /> <span>Night train</span></span>
      <span className={styles.mockPreviewLabel}>Illustrative workspace</span><span className={styles.mockLanguage}>EN <span>→</span> ML</span>
    </div>
    <div className={styles.mockWorkarea}>
      <aside className={styles.mockMedia} aria-hidden="true">
        <div className={styles.mockTabs}><FolderOpen size={13} /><span>Media</span><AudioLines size={13} /><SlidersHorizontal size={13} /></div>
        <div className={styles.mockClipThumb}><Image src="/images/landing-scene.png" alt="" width={1672} height={941} sizes="120px" /><span>01 — NIGHT TRAIN</span></div>
        <p>Scene 01 <span>00:08</span></p><div className={styles.mockFile}><Film size={13} /><span>night_train.mp4<small>Source media</small></span></div>
        <span className={styles.mockSectionLabel}>YOUR MEDIA. YOUR STORY.</span>
      </aside>
      <div className={styles.mockMonitor}>
        <div className={styles.mockMonitorLabel}><span>Source monitor</span><span>16:9</span></div>
        <div className={styles.mockStill}>
          <Image src="/images/landing-scene.png" alt="An illustrative film scene of a woman looking through a rain-streaked train window" width={1672} height={941} sizes="(max-width: 640px) 92vw, (max-width: 900px) 65vw, 760px" preload />
          <span className={styles.mockSubtitles} lang="ml">{line.malayalam}</span><span className={styles.mockSceneNumber}>SCENE 01 / NIGHT TRAIN</span>
        </div>
        <div className={styles.mockTransport}><button type="button" onClick={onToggle} aria-label={playing ? "Pause preview animation" : "Play preview animation"} aria-pressed={playing} className={styles.motionToggle}>
          {playing ? <Pause size={12} fill="currentColor" /> : <Play size={12} fill="currentColor" />}</button><span>{line.time} <small>/ 00:08.00</small></span><span className={styles.mockTransportNote}>Motion preview · no audio</span></div>
      </div>
      <aside className={styles.mockInspector} aria-label="Example dialogue">
        <div className={styles.mockInspectorHeading}><span>Dialogue</span><span>0{selection + 1} / 03</span></div>
        <div className={styles.mockSpeaker}><span>A</span><div>Speaker A<small>Line 0{selection + 1}</small></div><ChevronDown size={12} /></div>
        <div className={styles.mockField}><span>ENGLISH</span><p>{line.english}</p></div>
        <div className={styles.mockField}><span>MALAYALAM</span><p lang="ml">{line.malayalam}</p></div>
        <div className={styles.mockReview}><i /> Ready for your review</div>
      </aside>
    </div>
    <div className={styles.mockTimeline} role="group" aria-label="Illustrative timeline">
      <div className={styles.mockTimelineHeading}><span><Scissors size={11} /> Timeline</span><span>Select a line to explore <span>↙</span></span></div>
      <div className={styles.mockTracks} style={{ "--preview-playhead": line.position } as CSSProperties}>
        <div className={styles.mockTrackLabels}><span>SOURCE</span><span>DIALOGUE</span></div><div className={styles.mockTrackArea}>
          <div className={styles.previewWave} aria-hidden="true">{Array.from({ length: 84 }, (_, index) => <i key={index} style={{ height: `${Math.round(4 + Math.abs(Math.sin(index * 1.7) * Math.cos(index * .24)) * 19)}px`, "--bar-delay": `${index * -73}ms` } as CSSProperties} />)}</div>
          <div className={styles.mockDialogueTrack}>{LINES.map((item, index) => <button key={item.english} type="button" aria-label={`Preview line ${index + 1}`} aria-pressed={selection === index} onClick={() => setSelection(index)} className={selection === index ? styles.selectedMockLine : ""}><span>0{index + 1}</span>{item.english}</button>)}</div>
          <i className={styles.mockPlayhead} aria-hidden="true" />
        </div>
      </div>
    </div>
  </div>;
}
