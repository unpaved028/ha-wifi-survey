from wifi_survey.cleanup import CleanupParams, cleanup, join_corners, merge_collinear
from wifi_survey.walls import Segment

T = 30.0  # größte Wanddicke im Test


def seg(a, b, t=20.0, angle=0):
    return Segment(a, b, t, angle, 1.0)


def test_merges_fragments_but_keeps_openings():
    segs = [seg((0, 100), (200, 100)), seg((215, 101), (400, 101)),   # Lücke 15 px: Schraffur-Unterbrechung
            seg((470, 100), (600, 100))]                               # Lücke 70 px: Tür/Fenster
    out, merged = merge_collinear(segs, T, CleanupParams())
    assert merged == 1 and len(out) == 2
    long_ = max(out, key=lambda s: s.length())
    assert abs(min(long_.a[0], long_.b[0]) - 0) < 1 and abs(max(long_.a[0], long_.b[0]) - 400) < 1


def test_does_not_merge_different_thickness_or_offset():
    a = seg((0, 100), (200, 100), t=30)
    b = seg((200, 100), (400, 100), t=10)            # Dickensprung: bleibt getrennt
    c = seg((0, 140), (200, 140), t=20)              # parallel, aber 40 px versetzt
    out, merged = merge_collinear([a, b, c], T, CleanupParams())
    assert merged == 0 and len(out) == 3


def test_closes_corner_gap_and_t_junction():
    h = seg((0, 100), (300, 100), t=20)                      # endet 12 px vor der senkrechten Wand
    v = seg((332, 0), (332, 300), t=24, angle=90)
    stem = seg((150, 112), (150, 250), t=10, angle=90)       # T-Stoß von unten, berührt schon
    n = join_corners([h, v, stem], T, CleanupParams())
    assert n >= 1
    assert abs(h.b[0] - (332 + 12)) < 0.6                     # bis zur Außenkante der senkrechten Wand
    assert abs(min(stem.a[1], stem.b[1]) - (100 - 10)) < 0.6  # Stoß bis zur gegenüberliegenden Kante


def test_never_moves_the_far_end():
    piece = seg((268.5, 326.0), (306.5, 327.6), t=8)
    post = seg((306.5, 329.5), (306.5, 342.5), t=6, angle=90)
    join_corners([piece, post], T, CleanupParams())
    assert abs(piece.a[0] - 268.5) < 0.01                    # linkes Ende bleibt


def test_uncertain_pieces_are_not_attached():
    wall = seg((0, 100), (300, 100), t=20)
    junk = Segment((150, 130), (150, 200), 10.0, 90, 0.9, 0.5)   # unsicher (z. B. Treppe), 20 px vor der Wand
    join_corners([wall, junk], T, CleanupParams())
    assert junk.a == (150, 130)


def test_drops_tiny_and_duplicate_pieces():
    big = seg((0, 100), (300, 100), t=30)
    dup = seg((100, 102), (160, 102), t=20)                  # liegt ganz in der großen Wand
    tiny = seg((500, 500), (505, 500), t=20)                 # kürzer als halbe Dicke
    out, stats = cleanup([big, dup, tiny], T)
    assert out == [big] and stats.dropped == 2
