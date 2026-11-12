import copy
import json
import zipfile

import pytest

from app.services.gameio import (
    BundleError, BundleReader, GameBundle, RoundEntry, SongEntry, TicketEntry, manifest_dict, parse_manifest,
    sha256_file, write_bundle,
)


def make_bundle(size=3, songs=12, tickets=4):
    entries = [SongEntry(ref=i, title=f"Song {i}", artist=f"Artist {i}", tags="pop,80s", duration_ms=1000 + i,
                         start_ms=100, end_ms=900) for i in range(songs)]
    cells = [list(range(t, t + size * size)) for t in range(tickets)]
    return GameBundle("Pub Night", size, entries,
                      [RoundEntry(1, "Opener"), RoundEntry(2, "Full house", mode="full_house")],
                      [TicketEntry(n + 1, c) for n, c in enumerate(cells)])


def make_clips(tmp_path, bundle):
    files = {}
    for song in bundle.songs:
        path = tmp_path / f"src{song.ref}.mp3"
        path.write_bytes(f"audio-{song.ref}".encode() * 50)
        song.sha256 = sha256_file(path)
        files[song.ref] = path
    return files


def valid_manifest():
    return manifest_dict(make_bundle())


def test_manifest_round_trip():
    original = make_bundle()
    parsed = parse_manifest(json.loads(json.dumps(manifest_dict(original))))
    assert parsed.name == "Pub Night" and parsed.grid_size == 3
    assert [s.title for s in parsed.songs] == [s.title for s in original.songs]
    assert parsed.songs[0].tags == "pop,80s" and parsed.songs[0].start_ms == 100 and parsed.songs[0].end_ms == 900
    assert [(r.number, r.mode) for r in parsed.rounds] == [(1, "lines"), (2, "full_house")]
    assert [(t.number, t.cells) for t in parsed.tickets] == [(t.number, t.cells) for t in original.tickets]


def test_bundle_with_audio_round_trips_and_checksums_match(tmp_path):
    bundle = make_bundle()
    files = make_clips(tmp_path, bundle)
    path = tmp_path / "game.zip"
    write_bundle(path, bundle, files)
    with BundleReader(path) as reader:
        assert [s.clip for s in reader.bundle.songs][:2] == ["clips/0.mp3", "clips/1.mp3"]
        out = tmp_path / "copy.mp3"
        digest = reader.copy_clip(reader.bundle.songs[3], out)
        assert digest == reader.bundle.songs[3].sha256 == sha256_file(out)
        assert out.read_bytes() == files[3].read_bytes()


def test_bundle_without_audio_has_no_clips(tmp_path):
    bundle = make_bundle()
    make_clips(tmp_path, bundle)
    path = tmp_path / "game.zip"
    write_bundle(path, bundle, {})
    with zipfile.ZipFile(path) as z:
        assert z.namelist() == ["manifest.json"]
    with BundleReader(path) as reader:
        assert all(s.clip is None and s.sha256 for s in reader.bundle.songs)  # checksums still recorded


@pytest.mark.parametrize("change, message", [
    (lambda m: m.update(format="something-else"), "isn't a Track Bingo game file"),
    (lambda m: m.update(version=99), "newer version"),
    (lambda m: m.update(version="1"), "valid version"),
    (lambda m: m["game"].update(grid_size=2), "grid size"),
    (lambda m: m["game"].update(grid_size=10), "grid size"),
    (lambda m: m["game"].update(name="  "), "can't be empty"),
    (lambda m: m["game"].update(name="x" * 101), "too long"),
    (lambda m: m["songs"].__setitem__(0, "nope"), "malformed"),
    (lambda m: m["songs"][1].update(ref=0), "same reference"),
    (lambda m: m["songs"][0].update(title=5), "must be text"),
    (lambda m: m["songs"][0].update(end_ms=50), "before its start"),
    (lambda m: m["songs"][0].update(sha256="xyz"), "checksum"),
    (lambda m: m["songs"][0].update(clip="../evil.mp3"), "not allowed"),
    (lambda m: m["songs"][0].update(clip="clips/7.mp3"), "not allowed"),  # doesn't match its ref
    (lambda m: m.update(songs=m["songs"][:5]), "needs at least"),
    (lambda m: m["rounds"][0].update(mode="bogus"), "unknown pattern"),
    (lambda m: m["rounds"][0].update(lines_required=50), "Lines required"),
    (lambda m: m.update(rounds=[]), "at least one round"),
    (lambda m: m["tickets"][0].update(cells=[0, 1, 2]), "doesn't have 9 squares"),
    (lambda m: m["tickets"][0].update(cells=[99] * 9), "isn't in the game"),
    (lambda m: m["tickets"][0].update(cells=[0, 0, 1, 2, 3, 4, 5, 6, 7]), "repeats a song"),
    (lambda m: m["tickets"][1].update(number=1), "appears twice"),
    (lambda m: m.update(tickets=[]), "between 1 and"),
])
def test_bad_manifests_are_rejected_with_a_message(change, message):
    manifest = copy.deepcopy(valid_manifest())
    change(manifest)
    with pytest.raises(BundleError) as caught:
        parse_manifest(manifest)
    assert message in str(caught.value)


def test_not_a_manifest_at_all():
    for junk in (None, [], "text", 5, {}):
        with pytest.raises(BundleError):
            parse_manifest(junk)


def test_rounds_are_renumbered_in_order():
    manifest = valid_manifest()
    manifest["rounds"][0]["number"], manifest["rounds"][1]["number"] = 7, 3  # out of order and gappy
    parsed = parse_manifest(manifest)
    assert [(r.number, r.mode) for r in parsed.rounds] == [(1, "full_house"), (2, "lines")]


def zip_with(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_unsafe_or_unexpected_members_are_refused(tmp_path):
    manifest = json.dumps(valid_manifest())
    for name in ("../evil.txt", "/etc/passwd", "notes.txt", "clips/../../x.mp3", "clips/abc.mp3", "clips/1.exe", "other/manifest.json"):
        path = zip_with(tmp_path / "bad.zip", {"manifest.json": manifest, name: "x"})
        with pytest.raises(BundleError):
            BundleReader(path)


def test_not_a_zip_and_missing_manifest(tmp_path):
    (tmp_path / "plain.zip").write_bytes(b"this is not a zip file")
    with pytest.raises(BundleError):
        BundleReader(tmp_path / "plain.zip")
    with pytest.raises(BundleError):
        BundleReader(zip_with(tmp_path / "empty.zip", {"clips/0.mp3": "x"}))


def test_unreadable_manifest(tmp_path):
    with pytest.raises(BundleError):
        BundleReader(zip_with(tmp_path / "junk.zip", {"manifest.json": "{not json"}))


def test_a_clip_named_in_the_manifest_must_exist(tmp_path):
    bundle = make_bundle()
    files = make_clips(tmp_path, bundle)
    path = tmp_path / "game.zip"
    write_bundle(path, bundle, files)
    manifest = json.dumps(manifest_dict(bundle))
    with pytest.raises(BundleError) as caught:  # same manifest, but the audio has been stripped out
        BundleReader(zip_with(tmp_path / "stripped.zip", {"manifest.json": manifest}))
    assert "missing from the bundle" in str(caught.value)


def test_oversized_bundles_and_clips_are_refused(tmp_path):
    bundle = make_bundle()
    files = make_clips(tmp_path, bundle)
    path = tmp_path / "game.zip"
    write_bundle(path, bundle, files)
    with pytest.raises(BundleError):
        BundleReader(path, max_total_bytes=1000)  # unpacked size over the limit
    with BundleReader(path, max_clip_bytes=10) as reader, pytest.raises(BundleError):
        reader.copy_clip(reader.bundle.songs[0], tmp_path / "x.mp3")  # one clip over its cap
