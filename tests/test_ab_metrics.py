from eval.ab_metrics import count_hook_blocks_in_stream, measure_output, prose_without_code, sentence_lengths


def test_metrics_count_prose_and_ignore_code_for_semicolons():
    text = "Short sentence. This sentence has exactly six words today. `code; here`\n\n```py\nx; y\n```"
    measured = measure_output(text, hook_blocks=2)
    assert measured["sentence_count"] == 2
    assert measured["word_count"] == 14
    assert measured["semicolon_count_outside_code"] == 0
    assert measured["hook_blocks_met"] == 2


def test_mean_and_long_sentence_count():
    text = "one two three. " + " ".join(f"word{i}" for i in range(26)) + "."
    measured = measure_output(text)
    assert measured["sentence_count"] == 2
    assert measured["sentences_over_25_words"] == 1
    assert measured["mean_sentence_length"] == 14.5


def test_code_stripping_is_non_mutating_and_sentence_lengths_are_pure():
    text = "Keep this. `ignore; me.`"
    assert prose_without_code(text) == "Keep this.  "
    assert sentence_lengths(text) == [2]


def test_stream_counts_exit_code_two_block_fixture():
    from pathlib import Path
    stream = (Path(__file__).parent.parent / "eval" / "fixtures" / "blocked-hook-stream.jsonl").read_text(encoding="utf-8")
    assert count_hook_blocks_in_stream(stream) == 1
