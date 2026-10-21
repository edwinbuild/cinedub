"""Signal measurements adapter. Optional NumPy is imported only during local execution."""


class LocalPerformanceAnalyzer:
    name = "local"
    model = "acoustic-dsp-v1"

    def analyze(self, samples, *, offset_ms=0, word_count=0):
        from ..acoustics import measure_performance

        return measure_performance(samples, offset_ms=offset_ms, word_count=word_count)
