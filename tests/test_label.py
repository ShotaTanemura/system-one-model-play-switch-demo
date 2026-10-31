from s1play.label import death_frames, pick


def rows(lives):
    return [{"step": i, "life": life} for i, life in enumerate(lives)]


def test_death_frames_are_the_three_steps_before_a_life_increments():
    assert death_frames(rows([0, 0, 0, 0, 0, 1, 1])) == [2, 3, 4]


def test_death_frames_clamp_at_the_start_and_ignore_logs_without_lives():
    assert death_frames(rows([0, 1])) == [0]
    assert death_frames([{"step": 0}, {"step": 1}]) == []


def test_pick_keeps_every_death_frame_and_caps_the_total():
    runs = {"a": rows([0] * 10 + [1] * 10), "b": [{"step": i} for i in range(30)]}
    chosen = pick(runs, total=12)
    assert len(chosen) == 12
    assert pick(runs, total=40) == sorted(set(pick(runs, total=40)))
    assert {("a", 7), ("a", 8), ("a", 9)} <= set(pick(runs, total=40))
