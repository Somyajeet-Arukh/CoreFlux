from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'CoreFlux_Final_Project_Report.docx'
doc = Document()
sec = doc.sections[0]
sec.top_margin = Inches(.8)
sec.bottom_margin = Inches(.7)
sec.left_margin = Inches(.86)
sec.right_margin = Inches(.86)

styles = doc.styles
styles['Normal'].font.name = 'Aptos'
styles['Normal'].font.size = Pt(10.3)
styles['Normal'].font.color.rgb = RGBColor(30, 35, 40)
styles['Normal'].paragraph_format.space_after = Pt(6)
for name, size, before, after in [('Title', 23, 0, 12), ('Heading 1', 15, 15, 7), ('Heading 2', 11.5, 10, 4)]:
    st = styles[name]
    st.font.name = 'Aptos Display' if name == 'Title' else 'Aptos'
    st.font.size = Pt(size)
    st.font.bold = name != 'Title'
    st.font.color.rgb = RGBColor(0, 0, 0)
    st.paragraph_format.space_before = Pt(before)
    st.paragraph_format.space_after = Pt(after)
    st.paragraph_format.keep_with_next = True

def p(text='', style=None):
    return doc.add_paragraph(text, style)

def h(text, level=1):
    doc.add_heading(text, level)

def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), fill)
    tcPr.append(shd)

def borders(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    bd = OxmlElement('w:tcBorders')
    for side in ('top','left','bottom','right'):
        el = OxmlElement('w:'+side)
        el.set(qn('w:val'),'single')
        el.set(qn('w:color'),'D9D9D9')
        el.set(qn('w:sz'),'4')
        bd.append(el)
    tcPr.append(bd)

def table(headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, head in enumerate(headers):
        t.rows[0].cells[i].text = head
    for row in rows:
        cells = t.add_row().cells
        for i, value in enumerate(row): cells[i].text = str(value)
    if widths:
        for row in t.rows:
            for i, width in enumerate(widths): row.cells[i].width = Inches(width)
    for ri, row in enumerate(t.rows):
        for c in row.cells:
            c.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            borders(c)
            shade(c, '243A52' if ri == 0 else ('F3F6F9' if ri % 2 == 0 else 'FFFFFF'))
            for para in c.paragraphs:
                para.paragraph_format.space_after = Pt(2)
                para.paragraph_format.space_before = Pt(2)
                for run in para.runs:
                    run.font.size = Pt(8.6)
                    if ri == 0:
                        run.font.bold = True
                        run.font.color.rgb = RGBColor(255,255,255)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)

doc.add_paragraph('CoreFlux Final Project Report', 'Title')
p('Architecture, development progression, experimental findings and limitations')
p('24 October 2026')
h('Executive summary')
p('CoreFlux is a Linux resource-contention experiment framework completed through phases 0 to 9 for a WSL2 development environment. It observes real scheduler events using either a custom kernel module or an eBPF program, combines those observations with system signals to score contention, and can apply bounded, reversible controls to a specified workload. The final experiments characterize the module telemetry path under pressure and compare the two collection backends under matched controlled workloads.')
p('The central finding is operational rather than universal: the module delivered low-loss telemetry at the tested one-CPU stress settings through roughly 25,000 attempted events per second, while a higher tested point near 52,000 attempted events per second showed clear saturation. The backend comparison found differing stress-case loss, but the collectors used different buffer capacities and reader schedules. All numbers describe the documented WSL2 host and short controlled runs, not production workloads or bare-metal Linux.')

h('Project purpose and scope')
p('The project asks whether a small telemetry and intervention pipeline can observe resource contention, express a repeatable decision, make a temporary scheduling or cgroup change, and measure the behavior and cost of its own telemetry. It is an experimental framework, not a continuously operating production controller. Controlled workloads provide repeatable pressure; scheduler events and system counters are collected from the live WSL2 kernel. A synthetic event fixture tests serialization only and is excluded from performance conclusions.')

h('Final architecture')
p('The experiment flow is: controlled workload → live scheduler collector → JSONL events and system-signal windows → contention scorer → optional bounded policy action → reports and release checks. Collection, analysis and policy are separate executable tools; the policy does not run automatically merely because telemetry is enabled.')
h('Kernel module path', 2)
p('The custom module exposes a versioned /dev/coreflux ioctl control interface and bounded per-CPU rings through a shared mmap mapping. A userspace reader consumes scheduler-switch records, reports attempted, accepted, dropped, received and unread counts, and measures event-to-reader latency. The module remains observe-only; resource controls are applied by a separate userspace tool.')
h('eBPF path', 2)
p('The eBPF program attaches to the sched_switch tracepoint, sends equivalent scheduler-event fields through a BPF ring buffer, and maintains accepted and dropped counters. A loader reads and serializes the records. The two backends share an output shape but use different buffering and reader behavior; parity testing establishes matching event semantics rather than identical event counts.')
h('Analysis and intervention', 2)
p('The analysis tool scores timestamped windows using CPU pressure, runnable pressure, context-switch intensity, memory pressure and scheduler latency. It reports coverage and uses hysteresis and a cooldown for state transitions. The live event model lacks scheduler latency, so that signal is marked missing rather than invented. A CONTENTION or SEVERE decision can authorize a time-bounded policy action on a named CoreFlux workload: CPU affinity, nice priority or CPU cgroup quota. The tool records previous state and restores it on normal completion or handled termination.')

h('How the project progressed')
table(['Phase', 'Question answered and delivered work'], [
('0–1  Feasibility and foundation', 'Verified WSL2 module and eBPF capability; built the Docker workflow, event contract, workloads, recorder and no-telemetry baseline.'),
('2–4  Live observation', 'Added the versioned device ABI, per-CPU module rings and reader, then an eBPF collector with scheduler-event field parity.'),
('5–6  Decision and action', 'Built an explainable contention scorer; added dry-run-first, bounded affinity, priority and cgroup actions with rollback tests.'),
('7  Module characterization', 'Replaced the earlier hardware-counter objective with repeated throughput, loss, occupancy, latency, recovery and workload-overhead experiments.'),
('8  Backend comparison', 'Compared module and eBPF collectors under matched workload settings, while recording confounders and run-to-run variation.'),
('9  Hardening', 'Exercised malformed inputs, concurrency, mapping lifetime, cleanup and the full build-and-live-test sequence; recorded a release manifest.')
], [1.7, 5.0])
p('The Phase 7 revision was a deliberate scope correction. WSL2 did not expose a reliable hardware CPU PMU for IPC, cache-miss or branch-miss claims. The final Phase 7 therefore asks where the module telemetry stream becomes unreliable and how it recovers. Hardware-counter tools remain optional experiments, not a release gate.')

h('Methods and findings')
h('Contention detection and resource control', 2)
p('Two live analysis trials used a 48-thread CPU workload, eBPF scheduler events and host-wide pressure signals. Both reached CONTENTION with CPU pressure dominant; one also reached SEVERE. Replay tests checked thresholds, hysteresis, cooldown, custom weights and missing-signal behavior. This demonstrates a repeatable response to the fixture, not calibrated prediction accuracy. In a separate three-pair affinity experiment, moving the noisy workload to another allowed CPU improved the competing workload’s median throughput by 95.31% (individual pairs 95.06%–96.08%). This is a result for that defined isolation scenario.')
h('Module telemetry scalability', 2)
p('Phase 7 ran three two-second workload trials per setting with alternating baseline and module order. Collection was host-wide, and each module run used a fresh load and a roughly three-second reader window. Accounting distinguished attempted = accepted + dropped and accepted = received + accepted but unread. Per-CPU occupancy was sampled every 10 ms; recovery was tested by creating no-reader pressure before starting consumption.')
table(['Tested setting', 'Attempted/s', 'Received/s', 'Dropped', 'Peak occupancy'], [
('1 CPU, 2 stress threads', '25,076', '25,025', '0.20%', '62%'),
('1 CPU, 4 stress threads', '51,892', '41,395', '20.76%', '100%'),
('4 CPUs, 64 stress threads', '632,746', '202,607', '68.02%', '100%')
], [2.3, 1.1, 1.1, 1.0, 1.2])
p('All three trials of the two-thread one-CPU point met the report’s low-loss rule of at most 1% drops. All trials of the four-thread one-CPU point met its saturation rule of at least 5% loss plus a sampled full ring. The transition is bracketed between these tested points; it is not a guaranteed capacity threshold. After deliberate saturation, occupancy remained below 20% within 9.5–17.9 ms across three recovery trials (median 11.2 ms), and new events were received. The module mapping was 98,304 bytes for 24 possible CPU slots; the reader’s peak resident set was about 15 MiB and includes its runtime and libraries.')
p('Paired workload throughput differences were small and mixed in sign across the Phase 7 settings. They measure the workload with the module and reader together, not CPU time attributable solely to kernel code. Delivery latency describes received events only; dropped events have no measured delivery time. Sampled occupancy may miss short full-buffer bursts.')
h('Kernel module versus eBPF', 2)
p('Phase 8 used three short sequential baseline, module and eBPF observations per setting, alternating order. In the 16-worker, four-CPU stress case, the module read about 150,692 events/s with 13.9% median drop fraction, while eBPF read about 167,236 events/s with zero reported drops. The module used one page per possible CPU; the eBPF ring was configured at 64 KiB. Those unequal capacities, differing reader schedules, host-wide events and high run-to-run variability prevent a causal efficiency ranking. CPU-workload throughput differences were mixed, including apparent gains, so the short runs do not resolve small overhead differences.')

h('Verification and reproducibility')
p('The Phase 9 release check builds the user-space binaries, runs unit and integration checks, and exercises live module, eBPF, analysis, policy and comparison paths. It covers malformed device calls, concurrent control operations, ring overflow and ordering, shared mapping lifetime, reader geometry, backend event shape and rollback. The release manifest records source, binary and report hashes together with tool and kernel versions. The matching WSL kernel build tree is kept in a Docker volume; privileged tests attach to the shared WSL kernel. Generated report JSON files are ignored by version-control rules and should be retained when presenting numerical evidence.')

h('Interpretation and limits')
p('The project has completed its defined WSL2 experimental scope. It has not been validated against an external production dataset or deployed as a continuous production controller. Host-wide telemetry includes unrelated WSL activity; several experiments use only two- or three-second workloads and three repeats. Results are therefore environment-specific. A future native-Linux study would rebuild against that host’s kernel, verify the tracepoint layout, isolate or record host load, match buffer capacities, run longer randomized trials with more repeats, and validate against representative production traces or workloads where access and privacy allow.')

h('Repository evidence map')
p('README.md gives the runnable commands. docs/architecture.md and docs/abi.md specify the system and device contract. docs/contention-analysis.md, docs/resource-policy.md, docs/telemetry-scalability.md and docs/backend-comparison.md contain methods and detailed results. docs/release-hardening.md gives the full release workflow. Running the experiments writes machine-readable outputs under benchmarks/reports/, including release-manifest.json. The local project folder has no Git remote or history configured, so this document describes the project snapshot rather than a published release tag.')

doc.core_properties.title = 'CoreFlux Final Project Report'
doc.core_properties.subject = 'Architecture, progress, findings and limitations'
doc.save(OUT)
print(OUT)
