#!/usr/bin/env python3
"""GeoShake Seismic Signal Generator — Bass shaker test signals."""

import numpy as np
from scipy.signal import chirp
from scipy.io import wavfile
import os

SAMPLE_RATE = 44100


def generate_sine(freq, amplitude, duration):
    """Fixed-frequency sine wave."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    signal = amplitude * np.sin(2 * np.pi * freq * t)
    return t, signal


def generate_sweep(f1, f2, amplitude, duration):
    """Linear frequency sweep (chirp)."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    signal = amplitude * chirp(t, f0=f1, f1=f2, t1=duration, method='linear')
    return t, signal


def generate_burst(freq, amplitude, duration, decay):
    """Exponentially damped burst (P-wave or S-wave)."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    envelope = np.exp(-decay * t)
    signal = amplitude * envelope * np.sin(2 * np.pi * freq * t)
    return t, signal


def generate_earthquake(amplitude, duration):
    """Synthetic earthquake — P + S + surface waves + noise."""
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    signal = np.random.normal(0, 0.01, n)  # background noise

    def add_phase(f, amp, decay, start_pct, end_pct):
        s = int(start_pct * n)
        e = min(int(end_pct * n), n)
        length = e - s
        if length <= 0:
            return
        env = np.exp(-decay * np.linspace(0, 5, length))
        phase_t = np.linspace(0, (e - s) / SAMPLE_RATE, length)
        signal[s:e] += amp * env * np.sin(2 * np.pi * f * phase_t)

    # P-wave: 7%-17% (decay 1.5 — realistic intermediate)
    add_phase(5.0, amplitude * 0.3, 1.5, 0.07, 0.17)
    # S-wave: 17%-50%
    add_phase(2.0, amplitude * 0.8, 0.6, 0.17, 0.50)
    # Surface waves: 27%-77% (1.5 Hz — within bass shaker range)
    add_phase(1.5, amplitude * 1.0, 0.4, 0.27, 0.77)

    # Damping: 77%-100%
    damp_start = int(0.77 * n)
    fade = np.linspace(1.0, 0.0, n - damp_start)
    signal[damp_start:] *= fade

    # Normalize
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * amplitude

    return t, signal


def generate_noise(amplitude, duration):
    """Ambient noise — traffic rumble, HVAC hum, footstep impulses.

    For testing false-positive rejection of the STA/LTA detector.
    """
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False)
    signal = np.zeros(n)

    # Broadband random noise (traffic rumble)
    signal += np.random.normal(0, 0.3, n)

    # HVAC hum at ~15 Hz with harmonic
    signal += 0.2 * np.sin(2 * np.pi * 15 * t)
    signal += 0.1 * np.sin(2 * np.pi * 30 * t)

    # Random impulses (footsteps) — sporadic short bursts
    num_steps = int(duration * 2)
    for _ in range(num_steps):
        pos = np.random.randint(0, n)
        width = int(0.05 * SAMPLE_RATE)  # 50ms impulse
        end = min(pos + width, n)
        step_t = np.linspace(0, 1, end - pos)
        signal[pos:end] += (np.random.uniform(0.3, 0.8)
                            * np.exp(-10 * step_t)
                            * np.sin(2 * np.pi * 20 * step_t))

    # Normalize to amplitude
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * amplitude

    return t, signal


def generate_ramp(freq, amplitude, duration):
    """Linearly increasing amplitude sine — for threshold calibration.

    Play this while watching serial output to find the exact STA/LTA
    ratio at which the Allen CF triggers.
    """
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    envelope = np.linspace(0, 1, len(t))
    signal = amplitude * envelope * np.sin(2 * np.pi * freq * t)
    return t, signal


def generate_emergent_p(freq, amplitude, duration, rise_time):
    """Emergent P-wave with gradual onset (1-exp(-t/rise)).

    Tests whether Allen CF derivative term detects slow-onset P-waves,
    unlike impulsive bursts that always produce strong dx spikes.
    """
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    onset = 1 - np.exp(-t / max(rise_time, 0.01))
    decay = np.exp(-0.5 * t)
    signal = amplitude * onset * decay * np.sin(2 * np.pi * freq * t)
    return t, signal


def save_wav(filepath, signal):
    """Save signal as 16-bit PCM WAV."""
    data = np.clip(signal, -1.0, 1.0)
    data_int16 = (data * 32767).astype(np.int16)
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    wavfile.write(filepath, SAMPLE_RATE, data_int16)


import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# sounddevice import — graceful fallback if no audio device
try:
    import sounddevice as sd
    HAS_AUDIO = True
except (ImportError, OSError):
    HAS_AUDIO = False


class SeismicGeneratorApp:
    MODES = ['Sine', 'P-Wave', 'S-Wave', 'Sweep', 'Earthquake',
             'Noise', 'Ramp', 'Emergent P']
    MODE_DEFAULTS = {
        'Sine':       {'freq': 5.0},
        'P-Wave':     {'freq': 5.0, 'decay': 3.0},
        'S-Wave':     {'freq': 2.0, 'decay': 2.0},
        'Sweep':      {'f1': 2.0, 'f2': 50.0},
        'Earthquake': {'dur': 20.0},
        'Noise':      {},
        'Ramp':       {'freq': 5.0},
        'Emergent P': {'freq': 5.0, 'decay': 1.0},
    }

    def __init__(self, root):
        self.root = root
        self.root.title('GeoShake Seismic Signal Generator')
        self.root.geometry('800x650')
        self.root.resizable(False, False)
        self.root.configure(bg='#1c1c1e')

        self.mode = tk.StringVar(value='Sine')
        self.playing = False
        self._debounce_id = None
        self._playback_timer = None
        self._position_timer = None
        self._playback_start = 0.0
        self._playback_duration = 0.0

        self._build_ui()
        self._on_mode_change()

        self.root.bind('<space>', lambda e: self._play() if not self.playing else self._stop())
        self.root.bind('<Escape>', lambda e: self._stop())

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#1c1c1e')
        style.configure('TLabel', background='#1c1c1e', foreground='#f5f5f7',
                         font=('Helvetica', 12))
        style.configure('TScale', background='#1c1c1e')
        style.configure('Header.TLabel', font=('Helvetica', 18, 'bold'))
        style.configure('Val.TLabel', font=('Helvetica', 14, 'bold'),
                         foreground='#30d158')
        style.configure('Status.TLabel', font=('Helvetica', 10),
                         foreground='#86868b')

        main = ttk.Frame(self.root)
        main.pack(fill='both', expand=True, padx=16, pady=12)

        # Header
        ttk.Label(main, text='GeoShake Seismic Signal Generator',
                  style='Header.TLabel').pack(pady=(0, 12))

        # Mode buttons
        mode_frame = ttk.Frame(main)
        mode_frame.pack(fill='x', pady=(0, 12))
        for m in self.MODES:
            rb = tk.Radiobutton(mode_frame, text=m, variable=self.mode,
                                value=m, command=self._on_mode_change,
                                bg='#1c1c1e', fg='#f5f5f7',
                                selectcolor='#2c2c2e', activebackground='#2c2c2e',
                                font=('Helvetica', 11), indicatoron=0,
                                padx=12, pady=6, relief='flat', bd=0)
            rb.pack(side='left', padx=2)

        # Sliders
        slider_frame = ttk.Frame(main)
        slider_frame.pack(fill='x', pady=(0, 8))

        self.sliders = {}
        self.slider_labels = {}
        slider_defs = [
            ('freq',  'Frequency (Hz)', 0.5, 50.0, 5.0),
            ('amp',   'Amplitude',      0.0, 1.0,  0.5),
            ('dur',   'Duration (s)',   1.0, 60.0, 5.0),
            ('decay', 'Decay (α)',     0.5, 10.0, 3.0),
            ('f1',    'Sweep f₁ (Hz)', 0.5, 50.0, 1.0),
            ('f2',    'Sweep f₂ (Hz)', 0.5, 50.0, 50.0),
        ]

        for key, label, lo, hi, default in slider_defs:
            row = ttk.Frame(slider_frame)
            row.pack(fill='x', pady=3)
            lbl = ttk.Label(row, text=label, width=16)
            lbl.pack(side='left')
            var = tk.DoubleVar(value=default)
            scale = ttk.Scale(row, from_=lo, to=hi, variable=var,
                              orient='horizontal',
                              command=lambda *a: self._on_param_change())
            scale.pack(side='left', fill='x', expand=True, padx=8)
            val_lbl = ttk.Label(row, text=f'{default:.1f}', style='Val.TLabel',
                                width=6, anchor='e')
            val_lbl.pack(side='right')
            self.slider_labels[key] = lbl
            self.sliders[key] = (var, scale, val_lbl, row)

        # Buttons — use Canvas-based buttons for macOS dark theme compatibility
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill='x', pady=8)

        self.btn_play = self._make_button(btn_frame, '▶  Play', '#30d158', self._play)
        self.btn_play.pack(side='left', padx=4)

        self.btn_stop = self._make_button(btn_frame, '⏹  Stop', '#ff453a', self._stop)
        self.btn_stop.pack(side='left', padx=4)

        self.btn_save = self._make_button(btn_frame, '💾  Save WAV', '#636366', self._save_wav)
        self.btn_save.pack(side='left', padx=4)

        self.loop_var = tk.BooleanVar(value=False)
        loop_cb = tk.Checkbutton(btn_frame, text='Loop', variable=self.loop_var,
                                 bg='#1c1c1e', fg='#f5f5f7', selectcolor='#2c2c2e',
                                 activebackground='#1c1c1e', activeforeground='#f5f5f7',
                                 font=('Helvetica', 11))
        loop_cb.pack(side='left', padx=(12, 4))

        # Playback position indicator
        pos_frame = ttk.Frame(main)
        pos_frame.pack(fill='x', pady=(0, 4))

        self.pos_var = tk.StringVar(value='')
        self.pos_label = ttk.Label(pos_frame, textvariable=self.pos_var,
                                   style='Val.TLabel', anchor='w')
        self.pos_label.pack(side='left')

        self.progress_canvas = tk.Canvas(pos_frame, height=6, bg='#2c2c2e',
                                         highlightthickness=0, bd=0)
        self.progress_canvas.pack(side='left', fill='x', expand=True, padx=(8, 0))

        # Waveform canvas
        self.canvas_frame = ttk.Frame(main)
        self.canvas_frame.pack(fill='both', expand=True, pady=(8, 4))

        self.fig = Figure(figsize=(6, 2.2), dpi=100, facecolor='#1c1c1e')
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#000000')
        self.ax.tick_params(colors='#86868b', labelsize=8)
        self.ax.spines['bottom'].set_color('#2c2c2e')
        self.ax.spines['left'].set_color('#2c2c2e')
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        self.fig.subplots_adjust(left=0.08, right=0.98, top=0.95, bottom=0.18)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.canvas_frame)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)

        # Status bar
        self.status_var = tk.StringVar(value='Ready | 44100 Hz | Mono')
        ttk.Label(main, textvariable=self.status_var,
                  style='Status.TLabel').pack(anchor='w')

        if not HAS_AUDIO:
            self.status_var.set('⚠ No audio device found | WAV export works')
            self.btn_play.unbind('<Button-1>')

    def _make_button(self, parent, text, color, command):
        """Canvas-based button that renders colored backgrounds on macOS."""
        btn = tk.Canvas(parent, height=34, highlightthickness=0, bd=0, cursor='hand2')
        btn.configure(bg=color)
        btn._bg_color = color

        # Draw text centered
        def _draw(event=None):
            btn.delete('all')
            w, h = btn.winfo_width(), btn.winfo_height()
            btn.create_text(w // 2, h // 2, text=text, fill='white',
                            font=('Helvetica', 12, 'bold'))

        btn.bind('<Configure>', _draw)

        # Darken on hover
        def _enter(e):
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            darker = f'#{max(r-30,0):02x}{max(g-30,0):02x}{max(b-30,0):02x}'
            btn.configure(bg=darker)

        def _leave(e):
            btn.configure(bg=color)

        btn.bind('<Enter>', _enter)
        btn.bind('<Leave>', _leave)
        btn.bind('<Button-1>', lambda e: command())

        # Size to fit text
        btn.update_idletasks()
        btn.configure(width=len(text) * 10 + 24)

        return btn

    def _on_mode_change(self):
        mode = self.mode.get()
        defaults = self.MODE_DEFAULTS[mode]

        # Set defaults for this mode
        for key, value in defaults.items():
            if key in self.sliders:
                self.sliders[key][0].set(value)

        # Dynamic label for decay/rise slider
        if mode == 'Emergent P':
            self.slider_labels['decay'].configure(text='Rise time (s)')
        else:
            self.slider_labels['decay'].configure(text='Decay (α)')

        # Enable/disable sliders
        active = {
            'Sine':       ['freq', 'amp', 'dur'],
            'P-Wave':     ['freq', 'amp', 'dur', 'decay'],
            'S-Wave':     ['freq', 'amp', 'dur', 'decay'],
            'Sweep':      ['f1', 'f2', 'amp', 'dur'],
            'Earthquake': ['amp', 'dur'],
            'Noise':      ['amp', 'dur'],
            'Ramp':       ['freq', 'amp', 'dur'],
            'Emergent P': ['freq', 'amp', 'dur', 'decay'],
        }

        for key, (var, scale, val_lbl, row) in self.sliders.items():
            if key in active[mode]:
                scale.state(['!disabled'])
                val_lbl.configure(foreground='#30d158')
            else:
                scale.state(['disabled'])
                val_lbl.configure(foreground='#636366')

        self._on_param_change()

    def _on_param_change(self):
        # Update value labels
        for key, (var, scale, val_lbl, row) in self.sliders.items():
            val_lbl.configure(text=f'{var.get():.1f}')

        # Debounced preview update
        if self._debounce_id:
            self.root.after_cancel(self._debounce_id)
        self._debounce_id = self.root.after(200, self._update_preview)

    def _generate_signal(self):
        mode = self.mode.get()
        amp = self.sliders['amp'][0].get()
        dur = self.sliders['dur'][0].get()

        if mode == 'Sine':
            return generate_sine(self.sliders['freq'][0].get(), amp, dur)
        elif mode == 'Sweep':
            return generate_sweep(self.sliders['f1'][0].get(),
                                  self.sliders['f2'][0].get(), amp, dur)
        elif mode in ('P-Wave', 'S-Wave'):
            return generate_burst(self.sliders['freq'][0].get(), amp, dur,
                                  self.sliders['decay'][0].get())
        elif mode == 'Earthquake':
            return generate_earthquake(amp, dur)
        elif mode == 'Noise':
            return generate_noise(amp, dur)
        elif mode == 'Ramp':
            return generate_ramp(self.sliders['freq'][0].get(), amp, dur)
        elif mode == 'Emergent P':
            return generate_emergent_p(self.sliders['freq'][0].get(), amp, dur,
                                       self.sliders['decay'][0].get())
        else:
            raise ValueError(f'Unknown mode: {mode}')

    def _update_preview(self):
        t, signal = self._generate_signal()
        self.ax.clear()
        self.ax.set_facecolor('#000000')

        # Show first 5 seconds for long signals
        max_preview = 5.0
        dur = self.sliders['dur'][0].get()
        if dur > max_preview:
            n = int(max_preview * SAMPLE_RATE)
            t_plot, s_plot = t[:n], signal[:n]
            self.ax.set_xlabel(f'Time (s) — showing first {max_preview:.0f}s',
                              color='#86868b', fontsize=8)
        else:
            t_plot, s_plot = t, signal
            self.ax.set_xlabel('Time (s)', color='#86868b', fontsize=8)

        self.ax.plot(t_plot, s_plot, color='#30d158', linewidth=0.5)
        self.ax.set_ylabel('Amplitude', color='#86868b', fontsize=8)
        self.ax.set_ylim(-1.1, 1.1)
        self.ax.tick_params(colors='#86868b', labelsize=8)
        self.canvas.draw_idle()

    def _fmt_time(self, seconds):
        """Format seconds as M:SS."""
        m, s = divmod(int(seconds), 60)
        return f'{m}:{s:02d}'

    def _update_position(self):
        """Recurring timer to update playback position indicator."""
        if not self.playing:
            return
        import time
        elapsed = time.time() - self._playback_start
        if elapsed > self._playback_duration:
            elapsed = self._playback_duration
        total = self._playback_duration

        self.pos_var.set(f'{self._fmt_time(elapsed)} / {self._fmt_time(total)}')

        # Update progress bar
        self.progress_canvas.delete('all')
        w = self.progress_canvas.winfo_width()
        h = self.progress_canvas.winfo_height()
        if total > 0:
            pct = min(elapsed / total, 1.0)
            self.progress_canvas.create_rectangle(0, 0, int(w * pct), h,
                                                   fill='#30d158', outline='')

        self._position_timer = self.root.after(100, self._update_position)

    def _play(self):
        if not HAS_AUDIO:
            return
        if self.playing:
            sd.stop()
        if self._playback_timer:
            self.root.after_cancel(self._playback_timer)
        if self._position_timer:
            self.root.after_cancel(self._position_timer)
        t, signal = self._generate_signal()

        import time
        self._playback_duration = len(signal) / SAMPLE_RATE
        self._playback_start = time.time()

        sd.play(signal.astype(np.float32), SAMPLE_RATE)
        self.playing = True
        self.status_var.set(f'Playing... | {self.mode.get()} | {self._playback_duration:.1f}s')

        # Start position tracking
        self._update_position()

        # Update status when playback ends
        duration_ms = int(self._playback_duration * 1000)
        self._playback_timer = self.root.after(duration_ms, self._on_playback_done)

    def _on_playback_done(self):
        self._playback_timer = None
        if self._position_timer:
            self.root.after_cancel(self._position_timer)
            self._position_timer = None

        if self.loop_var.get() and self.playing:
            self._play()
            return

        self.playing = False
        self.pos_var.set(f'{self._fmt_time(self._playback_duration)} / {self._fmt_time(self._playback_duration)}')
        self.status_var.set('Ready | 44100 Hz | Mono')

        # Fill progress bar fully
        self.progress_canvas.delete('all')
        w = self.progress_canvas.winfo_width()
        h = self.progress_canvas.winfo_height()
        self.progress_canvas.create_rectangle(0, 0, w, h, fill='#30d158', outline='')

    def _stop(self):
        if self._playback_timer:
            self.root.after_cancel(self._playback_timer)
            self._playback_timer = None
        if self._position_timer:
            self.root.after_cancel(self._position_timer)
            self._position_timer = None
        if HAS_AUDIO:
            sd.stop()
        self.playing = False
        self.pos_var.set('')
        self.progress_canvas.delete('all')
        self.status_var.set('Ready | 44100 Hz | Mono')

    def _save_wav(self):
        t, signal = self._generate_signal()
        output_dir = os.path.join(os.path.dirname(__file__), 'output')
        os.makedirs(output_dir, exist_ok=True)
        filepath = filedialog.asksaveasfilename(
            initialdir=output_dir,
            defaultextension='.wav',
            filetypes=[('WAV files', '*.wav')],
            initialfile=f'{self.mode.get().lower()}_{self.sliders["dur"][0].get():.0f}s.wav'
        )
        if filepath:
            try:
                save_wav(filepath, signal)
                self.status_var.set(f'Saved: {os.path.basename(filepath)}')
            except Exception as e:
                messagebox.showerror('Error', f'Failed to save WAV:\n{e}')


def main():
    root = tk.Tk()
    app = SeismicGeneratorApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
