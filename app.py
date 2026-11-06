"""칼바람 딜량 내기 기록소 — Streamlit 앱.

핵심 흐름: 사진 업로드 → 폴더(날짜) 저장 → OCR 초안 → 표에서 수정 → 경기 저장 → 합계/정산.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "aram"))

import champions  # noqa: E402
import db  # noqa: E402
import importer  # noqa: E402
import metrics  # noqa: E402
import ocr  # noqa: E402
import settle  # noqa: E402

st.set_page_config(page_title="칼바람 딜량 기록소", page_icon="🎯", layout="wide")
db.init()

CSS = """
<style>
.block-container{padding-top:2.2rem;padding-bottom:3rem;max-width:1280px}
h1,h2,h3{letter-spacing:-.02em}
[data-testid="stMetricValue"]{font-size:1.5rem}
div[data-testid="stMetric"]{background:#fff;border:1px solid #dde3e0;padding:12px 14px}
.small{font-size:.82rem;color:#5f727d}
.tag{display:inline-block;background:#eaf2f4;color:#1b5f78;padding:2px 7px;border-radius:3px;font-size:.75rem;margin-right:4px}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def mmss(sec) -> str:
    if sec is None or pd.isna(sec):
        return "—"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def parse_duration(text: str) -> int | None:
    text = (text or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return int(text)
    m = re.fullmatch(r"(\d{1,3})[:분](\d{1,2})", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def money(v: float) -> str:
    return f"{v:,.0f}원"


def folder_select(key: str, index: int = 0) -> int:
    folders = db.list_folders()
    if not folders:
        return db.ensure_today_folder()
    labels = {f"{f['name']} · {f['games']}경기": f["id"] for f in folders}
    picked = st.selectbox("폴더 선택", list(labels), index=min(index, len(labels) - 1), key=key)
    return labels[picked]


def entry_df(rows: list[dict] | None = None, slots: int = 5) -> pd.DataFrame:
    cols = ["아이디", "팀", "챔피언", "딜량", "순위", "골드"]
    if rows:
        df = pd.DataFrame(rows)
        for c in cols:
            if c not in df:
                df[c] = None
        return df[cols]
    return pd.DataFrame({c: [None] * slots for c in cols})


def entry_editor(df: pd.DataFrame, key: str, players: list[str]) -> pd.DataFrame:
    champ_names = list(champions.names())
    return st.data_editor(
        df, key=key, num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={
            "아이디": st.column_config.TextColumn("아이디", help="기록에 남길 소환사 이름", width="medium"),
            "팀": st.column_config.SelectboxColumn("팀", options=["아군", "적군"], default="아군", width="small"),
            "챔피언": st.column_config.SelectboxColumn("챔피언", options=champ_names, width="medium"),
            "딜량": st.column_config.NumberColumn("딜량", min_value=0, step=100, format="%d"),
            "순위": st.column_config.NumberColumn("팀내 순위", min_value=1, max_value=10, step=1),
            "골드": st.column_config.NumberColumn("골드", min_value=0, step=100, format="%d"),
        },
    )


def clean_entries(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        player = str(r.get("아이디") or "").strip()
        if not player or player.lower() == "none":
            continue
        dmg = r.get("딜량")
        out.append({
            "player": player,
            "team": r.get("팀") or "아군",
            "champion": str(r.get("챔피언") or "").strip(),
            "damage": int(dmg) if pd.notna(dmg) else None,
            "dmg_rank": int(r["순위"]) if pd.notna(r.get("순위")) else None,
            "gold": int(r["골드"]) if pd.notna(r.get("골드")) else None,
            "bet_member": 1, "note": "",
        })
    return out


def folder_kpis(df: pd.DataFrame) -> None:
    t = metrics.folder_totals(df)
    c = st.columns(6)
    c[0].metric("경기", f"{t['경기']}판")
    c[1].metric("기록", f"{t['기록']}건")
    c[2].metric("딜량합계", f"{t['딜량합계']:,.0f}")
    c[3].metric("평균 딜량", f"{t['평균딜량']:,.0f}" if t["평균딜량"] else "—")
    c[4].metric("평균 순위", f"{t['평균순위']:.2f}위" if t["평균순위"] else "—")
    c[5].metric("평균 DPS", f"{t['평균DPS']:,.0f}" if t["평균DPS"] else "—")


def show_entries_with_share(entries: list[dict], duration: int | None) -> None:
    if not entries:
        st.info("이 경기에는 아직 기록이 없습니다.")
        return
    df = pd.DataFrame(entries)
    df["딜량"] = pd.to_numeric(df["damage"], errors="coerce")
    teams = df.groupby("team")["딜량"].sum(min_count=1)
    df["지분"] = df.apply(
        lambda r: r["딜량"] / teams.get(r["team"]) if pd.notna(r["딜량"]) and teams.get(r["team"]) else None, axis=1)
    df["DPS"] = df["딜량"] / duration if duration else None
    df["DPM"] = df["DPS"] * 60 if duration else None
    view = df.rename(columns={"player": "아이디", "team": "팀", "champion": "챔피언",
                              "damage": "딜량", "dmg_rank": "순위", "gold": "골드"})
    st.dataframe(
        view[["아이디", "팀", "챔피언", "딜량", "순위", "지분", "DPS", "DPM", "골드"]],
        hide_index=True, use_container_width=True,
        column_config={
            "딜량": st.column_config.NumberColumn(format="%d"),
            "지분": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=1),
            "DPS": st.column_config.NumberColumn(format="%.0f"),
            "DPM": st.column_config.NumberColumn(format="%.0f"),
            "골드": st.column_config.NumberColumn(format="%d"),
        })


# ------------------------------------------------------------------ pages
def page_upload() -> None:
    st.subheader("사진 업로드 · OCR")
    st.caption("사진은 선택한 폴더에 저장되고, OCR 결과는 초안입니다. 표에서 고친 뒤 저장하세요.")

    folders = db.list_folders()
    today_id = db.ensure_today_folder()
    left, right = st.columns([3, 2])
    with left:
        labels = {f"{f['name']} · {f['games']}경기": f["id"] for f in folders} or {"(없음)": today_id}
        default_label = next((k for k, v in labels.items() if v == today_id), list(labels)[0])
        folder_label = st.selectbox("저장할 폴더", list(labels), index=list(labels).index(default_label))
        folder_id = labels[folder_label]
    with right:
        with st.popover("새 폴더 만들기", use_container_width=True):
            with st.form("new_folder"):
                name = st.text_input("폴더 이름", value=dt.date.today().isoformat())
                fdate = st.date_input("날짜", value=dt.date.today())
                note = st.text_input("메모", placeholder="예: 11/6 저녁 내기")
                if st.form_submit_button("만들기", type="primary"):
                    try:
                        new_id = db.create_folder(name, note, fdate.isoformat())
                        st.success(f"폴더 생성: {name}")
                        st.session_state["folder_pick"] = new_id
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))

    files = st.file_uploader("사진 여러 장 선택 (PNG/JPG)", type=["png", "jpg", "jpeg", "webp"],
                             accept_multiple_files=True)
    c1, c2, c3 = st.columns([2, 2, 3])
    bets = db.list_bets(folder_id)
    bet_labels = {"내기 없음": None} | {f"{b['name']} ({b['stake']:,}원)": b["id"] for b in bets}
    with c1:
        bet_label = st.selectbox("내기 구간", list(bet_labels))
    with c2:
        duration_text = st.text_input("경기 시간 (mm:ss)", placeholder="예: 18:24",
                                      help="모든 사진에 같은 값을 적용합니다. 사진마다 다르면 저장 후 수정하세요.")
    with c3:
        result = st.selectbox("아군 결과", ["미기록", "승", "패"])
    merge = st.checkbox("업로드한 사진들을 한 경기로 묶기", help="아군/적군 화면처럼 같은 경기를 나눠 찍은 경우")

    if st.button("사진 저장 + OCR 실행", type="primary", disabled=not files):
        dur = parse_duration(duration_text)
        known = db.known_players()
        ids = []
        progress = st.progress(0.0, text="사진을 저장하고 글자를 읽는 중…")
        for i, f in enumerate(files, 1):
            img_id = db.add_image(folder_id, f.name, f.getvalue())
            res = ocr.read_text(f.getvalue())
            rows = ocr.parse_lines(res.get("lines", []), known)
            db.update_image_ocr(img_id, res.get("text", ""), res.get("conf"),
                                rows, "인식 완료" if rows else "수동 입력 필요")
            ids.append(img_id)
            progress.progress(i / len(files), text=f"{f.name} 처리 중… ({i}/{len(files)})")
        st.session_state["upload_ids"] = ids
        st.session_state["upload_meta"] = {"dur": dur, "result": None if result == "미기록" else result,
                                           "bet": bet_labels[bet_label], "merge": merge, "folder": folder_id}
        progress.empty()
        st.success(f"{len(ids)}장 저장 · OCR 완료. 아래에서 확인하고 저장하세요.")
        st.rerun()

    ids = [i for i in st.session_state.get("upload_ids", []) if i]
    if not ids:
        return
    meta = st.session_state.get("upload_meta", {})
    images = {img["id"]: img for img in db.list_images(folder_id)}
    ids = [i for i in ids if i in images]
    if not ids:
        return

    st.divider()
    if meta.get("merge"):
        st.markdown("#### 묶은 사진 → 한 경기")
        rows = []
        for img_id in ids:
            rows += images[img_id]["rows"]
        edited = entry_editor(entry_df(rows), "merge_editor", db.known_players())
        if st.button("이 경기로 저장", type="primary", key="save_merge"):
            _save_game(folder_id, meta, edited, ids)
    else:
        tabs = st.tabs([images[i]["filename"] for i in ids])
        for img_id, tab in zip(ids, tabs):
            img = images[img_id]
            with tab:
                a, b = st.columns([3, 2])
                with a:
                    st.image(str(img["path"]), use_container_width=True)
                with b:
                    st.markdown(f"**상태** {img['status']} · 신뢰도 {img['ocr_conf'] or 0:.0f}")
                    with st.expander("인식된 원문 보기"):
                        st.text(img["ocr_text"] or "(인식된 글자 없음)")
                    players = db.known_players()
                    cands = ocr.player_candidates([{"words": w} for w in (img.get("ocr_text") or "").split()], players)
                    st.caption("사진에서 찾은 아이디 후보: " + (", ".join(cands) if cands else "없음"))
                edited = entry_editor(entry_df(img["rows"]), f"editor_{img_id}", db.known_players())
                if st.button("이 경기로 저장", type="primary", key=f"save_{img_id}"):
                    _save_game(folder_id, meta, edited, [img_id])


def _save_game(folder_id: int, meta: dict, edited: pd.DataFrame, image_ids: list[int]) -> None:
    rows = clean_entries(edited)
    if not rows:
        st.error("아이디와 딜량이 있는 행이 하나도 없습니다.")
        return
    for r in rows:
        if not r["damage"]:
            st.warning(f"{r['player']} 의 딜량이 비어 있습니다.")
    seq = db.next_seq(folder_id)
    game_id = db.append_game(
        folder_id, label=f"{seq}경기", played_at="", duration_sec=meta.get("dur"),
        result=meta.get("result"), bet_id=meta.get("bet"), image_id=image_ids[0],
        note="; ".join(f"사진 {i}" for i in image_ids))
    db.replace_entries(game_id, rows)
    st.success(f"{seq}경기 저장 완료 · {len(rows)}명")
    st.session_state["upload_ids"] = []
    st.rerun()


def page_folder() -> None:
    st.subheader("폴더 · 경기 기록")
    folder_id = folder_select("folder_page")
    folder = db.get_folder(folder_id)
    if not folder:
        return
    df = metrics.entries([folder_id])
    folder_kpis(df)
    st.caption(f"폴더 `{folder['name']}` · {folder['folder_date']} · {folder['note']}")

    with st.expander("새 경기 추가 (중간 삽입 가능)"):
        games = db.list_games(folder_id)
        with st.form("add_game"):
            c1, c2, c3 = st.columns(3)
            pos = c1.number_input("경기 번호", min_value=1, value=len(games) + 1, step=1)
            dur = c2.text_input("경기 시간 (mm:ss)", placeholder="18:24")
            res = c3.selectbox("결과", ["미기록", "승", "패"])
            if st.form_submit_button("추가", type="primary"):
                db.insert_game(folder_id, int(pos), label=f"{int(pos)}경기",
                               duration_sec=parse_duration(dur),
                               result=None if res == "미기록" else res)
                st.rerun()

    games = db.list_games(folder_id)
    if not games:
        st.info("아직 경기가 없습니다. 사진을 올리거나 위에서 빈 경기를 추가하세요.")
    bets = {b["id"]: b for b in db.list_bets(folder_id)}
    for g in games:
        entries = db.list_entries(g["id"])
        head = (f"{g['seq']}. {g['label'] or ''} · {len(entries)}명 · "
                f"{g['total_damage']:,} · {mmss(g['duration_sec'])} · "
                f"{(g['bet_name'] or '내기 없음')} · {g['result'] or '결과 미기록'}")
        with st.expander(head):
            show_entries_with_share(entries, g["duration_sec"])
            with st.form(f"meta_{g['id']}"):
                c1, c2, c3, c4 = st.columns(4)
                label = c1.text_input("라벨", value=g["label"] or "")
                dur = c2.text_input("경기 시간 (mm:ss)", value=mmss(g["duration_sec"]).replace("—", ""))
                res = c3.selectbox("결과", ["미기록", "승", "패"],
                                   index=["미기록", "승", "패"].index(g["result"] or "미기록"))
                bet_keys = [None] + list(bets)
                bet_labels = ["내기 없음"] + [bets[b]["name"] for b in bets]
                bet_sel = c4.selectbox("내기 구간", bet_labels,
                                       index=bet_keys.index(g["bet_id"]) if g["bet_id"] in bet_keys else 0)
                note = st.text_input("메모", value=g["note"] or "")
                if st.form_submit_button("경기 정보 저장"):
                    db.update_game(g["id"], label=label, duration_sec=parse_duration(dur),
                                   result=None if res == "미기록" else res,
                                   bet_id=bet_keys[bet_labels.index(bet_sel)], note=note)
                    st.rerun()
            edited = entry_editor(entry_df(entries), f"edit_{g['id']}", db.known_players())
            c1, c2 = st.columns([1, 1])
            if c1.button("참가기록 저장", key=f"save_e_{g['id']}", type="primary"):
                db.replace_entries(g["id"], clean_entries(edited))
                st.rerun()
            if c2.button("경기 삭제", key=f"del_{g['id']}"):
                db.delete_game(g["id"])
                st.rerun()

    st.divider()
    st.markdown("#### 사진 관리")
    images = db.list_images(folder_id)
    if not images:
        st.caption("이 폴더에 사진이 없습니다.")
    else:
        others = {f"{f['name']}": f["id"] for f in db.list_folders() if f["id"] != folder_id}
        for img in images:
            c1, c2, c3 = st.columns([1, 2, 2])
            c1.image(str(img["path"]), width=140)
            c2.write(f"**{img['filename']}**")
            c2.caption(f"{img['status']} · 신뢰도 {img['ocr_conf'] or 0:.0f}")
            if others:
                target = c3.selectbox("다른 폴더로 이동", ["(선택)"] + list(others), key=f"mv_{img['id']}")
                if target != "(선택)" and c3.button("이동", key=f"mvbtn_{img['id']}"):
                    db.move_image(img["id"], others[target])
                    st.rerun()
            if c3.button("사진 삭제", key=f"delimg_{img['id']}"):
                db.delete_image(img["id"])
                st.rerun()


def page_summary() -> None:
    st.subheader("오늘 · 폴더 합계")
    folder_id = folder_select("sum_page")
    folder = db.get_folder(folder_id)
    df = metrics.entries([folder_id])
    folder_kpis(df)
    st.caption(f"폴더 `{folder['name']}` · {folder['folder_date']}")

    tabs = st.tabs(["아이디별", "경기별", "내기 구간", "정산", "사진"])
    with tabs[0]:
        team = st.radio("기준", ["아군", "적군", "전체"], horizontal=True, key="sum_team")
        table = metrics.player_table(df, None if team == "전체" else team)
        if table.empty:
            st.info("기록이 없습니다.")
        else:
            st.dataframe(table, hide_index=True, use_container_width=True, column_config={
                "평균딜량": st.column_config.NumberColumn(format="%.0f"),
                "딜량합계": st.column_config.NumberColumn(format="%.0f"),
                "평균순위": st.column_config.NumberColumn(format="%.2f"),
                "평균DPS": st.column_config.NumberColumn(format="%.0f"),
                "평균DPM": st.column_config.NumberColumn(format="%.0f"),
                "골드합계": st.column_config.NumberColumn(format="%.0f"),
                "승률": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=1),
            })
    with tabs[1]:
        games = metrics.game_table(df)
        if games.empty:
            st.info("기록이 없습니다.")
        else:
            games["경기시간"] = games["경기시간(초)"].apply(mmss)
            st.dataframe(games[["경기", "인원", "딜량합계", "경기시간", "팀DPS합", "승패"]],
                         hide_index=True, use_container_width=True)
            for _, g in games.iterrows():
                sub = df[df["game_id"] == g["game_id"]]
                with st.expander(f"{int(g['경기'])}경기 상세 · {int(g['인원'])}명"):
                    show_entries_with_share(sub.to_dict("records"), g["경기시간(초)"])
    with tabs[2]:
        bets = db.list_bets(folder_id)
        if not bets:
            st.info("내기 구간이 없습니다. 아래에서 추가하세요.")
        for b in bets:
            bdf = df[df["bet_id"] == b["id"]] if not df.empty else df
            st.markdown(f"**{b['name']}** · {b['stake']:,}원 · {b['rule']} · "
                        f"{bdf['game_id'].nunique() if not bdf.empty else 0}경기")
            if not bdf.empty:
                st.dataframe(metrics.player_table(bdf, None), hide_index=True, use_container_width=True,
                             column_config={"평균딜량": st.column_config.NumberColumn(format="%.0f"),
                                            "평균순위": st.column_config.NumberColumn(format="%.2f"),
                                            "평균DPS": st.column_config.NumberColumn(format="%.0f"),
                                            "평균DPM": st.column_config.NumberColumn(format="%.0f"),
                                            "승률": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=1)})
        with st.form("bet_form"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("구간 이름", placeholder="2~4경기")
            stake = c2.number_input("1인당 금액(원)", min_value=0, value=1000, step=1000)
            rule = c3.selectbox("정산 규칙", list(settle.RULES))
            if st.form_submit_button("구간 추가"):
                db.upsert_bet(None, folder_id, name or "새 구간", int(stake), rule)
                st.rerun()
    with tabs[3]:
        bets = db.list_bets(folder_id)
        if not bets or df.empty:
            st.info("정산할 내기 구간이 없습니다.")
        else:
            labels = {b["name"]: b for b in bets}
            picked = st.selectbox("내기 구간", list(labels), key="settle_bet")
            b = labels[picked]
            stake = st.number_input("1인당 금액(원)", min_value=0, value=int(b["stake"] or 1000), step=1000)
            rule = st.selectbox("규칙", list(settle.RULES), index=list(settle.RULES).index(b["rule"]) if b["rule"] in settle.RULES else 0)
            bdf = df[(df["bet_id"] == b["id"]) & (df["team"] == "아군") & df["dmg_rank"].notna()]
            if bdf.empty:
                st.info("이 구간에 순위가 있는 아군 기록이 없습니다.")
            else:
                rank_sums = bdf.groupby("player")["dmg_rank"].sum().astype(int).to_dict()
                game_ranks = [g.set_index("player")["dmg_rank"].astype(int).to_dict()
                              for _, g in bdf.groupby("game_id")]
                net = settle.settle(rank_sums, game_ranks, int(stake), rule)
                view = pd.DataFrame({"아이디": list(net), "정산": list(net.values())})
                view["순위합"] = view["아이디"].map(rank_sums)
                st.dataframe(view.sort_values("정산", ascending=False), hide_index=True,
                             use_container_width=True,
                             column_config={"정산": st.column_config.NumberColumn(format="%d원")})
                st.caption(f"합계 {sum(net.values()):,}원 (0원이어야 정상) · 순위합이 낮을수록 상위")
    with tabs[4]:
        images = db.list_images(folder_id)
        if images:
            cols = st.columns(3)
            for i, img in enumerate(images):
                cols[i % 3].image(str(img["path"]), caption=img["filename"], use_container_width=True)
        else:
            st.caption("사진이 없습니다.")


def page_overall() -> None:
    st.subheader("전체 종합")
    folders = db.list_folders()
    if not folders:
        st.info("기록이 없습니다.")
        return
    labels = {f"{f['name']} ({f['games']})": f["id"] for f in folders}
    picked = st.multiselect("폴더", list(labels), default=list(labels))
    ids = [labels[p] for p in picked]
    df = metrics.entries(ids)
    if df.empty:
        st.info("선택한 폴더에 기록이 없습니다.")
        return
    c1, c2 = st.columns([1, 3])
    team = c1.radio("기준", ["아군", "적군", "전체"], horizontal=True)
    min_games = c2.slider("최소 경기 수", 1, 20, 1)
    table = metrics.player_table(df, None if team == "전체" else team, min_games)
    st.markdown("#### 참가자 종합")
    st.dataframe(table, hide_index=True, use_container_width=True, column_config={
        "평균딜량": st.column_config.NumberColumn(format="%.0f"),
        "딜량합계": st.column_config.NumberColumn(format="%.0f"),
        "평균순위": st.column_config.NumberColumn(format="%.2f"),
        "평균DPS": st.column_config.NumberColumn(format="%.0f"),
        "평균DPM": st.column_config.NumberColumn(format="%.0f"),
        "골드합계": st.column_config.NumberColumn(format="%.0f"),
        "승률": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=1),
    })
    if not table.empty:
        a, b = st.columns(2)
        a.caption("평균 순위 (낮을수록 좋음)")
        a.bar_chart(table.set_index("아이디")["평균순위"])
        b.caption("평균 딜량")
        b.bar_chart(table.set_index("아이디")["평균딜량"])

    tabs = st.tabs(["캐릭터", "함께한 사람", "폴더 비교", "다운로드"])
    with tabs[0]:
        champ = metrics.champion_table(df, 1)
        if champ.empty:
            st.info("캐릭터 기록이 없습니다.")
        else:
            st.dataframe(champ, hide_index=True, use_container_width=True, height=420,
                         column_config={"평균딜량": st.column_config.NumberColumn(format="%.0f"),
                                        "평균순위": st.column_config.NumberColumn(format="%.2f"),
                                        "평균DPS": st.column_config.NumberColumn(format="%.0f")})
    with tabs[1]:
        pairs = metrics.pair_table(df)
        if pairs.empty:
            st.info("같은 경기에 기록된 참가자가 없습니다.")
        else:
            st.dataframe(pairs, hide_index=True, use_container_width=True, height=420,
                         column_config={"함께 승률": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=1)})
    with tabs[2]:
        rows = []
        for fid in ids:
            sub = df[df["folder_id"] == fid]
            t = metrics.folder_totals(sub)
            rows.append({"폴더": sub["folder_name"].iloc[0], "경기": t["경기"], "기록": t["기록"],
                         "딜량합계": t["딜량합계"], "평균딜량": t["평균딜량"],
                         "평균순위": t["평균순위"], "평균DPS": t["평균DPS"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={"딜량합계": st.column_config.NumberColumn(format="%.0f"),
                                    "평균딜량": st.column_config.NumberColumn(format="%.0f"),
                                    "평균순위": st.column_config.NumberColumn(format="%.2f"),
                                    "평균DPS": st.column_config.NumberColumn(format="%.0f")})
    with tabs[3]:
        st.download_button("참가자 종합 CSV", table.to_csv(index=False).encode("utf-8-sig"),
                           file_name="참가자_종합.csv", mime="text/csv")
        st.download_button("전체 기록 CSV", df.drop(columns=["result"]).to_csv(index=False).encode("utf-8-sig"),
                           file_name="전체_기록.csv", mime="text/csv")


def page_settings() -> None:
    st.subheader("설정 · 백업 · 가져오기")
    status = ocr.status()
    c1, c2, c3 = st.columns(3)
    c1.metric("Tesseract", status.get("version") or "없음")
    c2.metric("한국어(kor)", "사용 가능" if status.get("kor") else "없음")
    c3.metric("저장 위치", "로컬" if not str(db.BASE).startswith("/mount") else "마운트")
    if status.get("message"):
        st.warning(status["message"])
    st.caption(f"데이터 폴더: `{db.BASE}` — Streamlit Cloud는 재시작 시 초기화될 수 있으니 아래 백업을 주기적으로 받으세요.")

    st.markdown("#### 백업 / 복원")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in Path(db.BASE).rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(db.BASE))
    st.download_button("전체 백업 ZIP 내려받기", buf.getvalue(),
                       file_name=f"aram_backup_{dt.datetime.now():%Y%m%d_%H%M}.zip", mime="application/zip")
    up = st.file_uploader("백업 ZIP 복원 (같은 이름 파일은 덮어씁니다)", type=["zip"], key="restore")
    if up and st.button("복원 실행"):
        with zipfile.ZipFile(io.BytesIO(up.getvalue())) as z:
            for name in z.namelist():
                if name.endswith("/") or ".." in name:
                    continue
                target = Path(db.BASE) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
        st.success("복원 완료")
        st.rerun()

    st.markdown("#### 기존 엑셀·CSV 가져오기")
    f = st.file_uploader("파일 선택 (xlsx/csv)", type=["xlsx", "xlsm", "csv"], key="import")
    if f:
        try:
            parsed = importer.read_any(f.getvalue(), f.name)
        except Exception as exc:
            st.error(f"읽기 실패: {exc}")
            parsed = pd.DataFrame()
        if parsed.empty:
            st.warning("인식 가능한 기록이 없습니다. 날짜·경기·아이디·챔피언·딜량·순위 열이 있는지 확인하세요.")
        else:
            st.dataframe(parsed.head(30), use_container_width=True, hide_index=True)
            folder_name = st.text_input("가져올 폴더 이름", value=Path(f.name).stem)
            if st.button("가져오기 실행", type="primary"):
                fid = db.create_folder(folder_name, "엑셀 가져오기")
                for (date, game), g in parsed.groupby(["date", "game"], sort=False):
                    seq = db.next_seq(fid)
                    gid = db.append_game(fid, label=f"{g['game'].iloc[0] or seq}경기", note=str(date))
                    rows = [{"player": r["player"], "team": r.get("team") or "아군",
                             "champion": r.get("champion") or "", "damage": int(r["damage"]),
                             "dmg_rank": int(r["rank"]) if pd.notna(r["rank"]) else None,
                             "gold": int(r["gold"]) if pd.notna(r.get("gold")) else None,
                             "bet_member": 1, "note": ""} for _, r in g.iterrows()]
                    db.replace_entries(gid, rows)
                st.success(f"{folder_name} 폴더로 가져왔습니다.")
                st.rerun()

    st.markdown("#### 폴더 관리")
    folders = db.list_folders()
    if folders:
        labels = {f"{f['name']} · {f['games']}경기": f["id"] for f in folders}
        pick = st.selectbox("폴더", list(labels), key="manage")
        fid = labels[pick]
        with st.form("rename"):
            new_name = st.text_input("새 이름", value=pick.split(" · ")[0])
            if st.form_submit_button("이름 변경"):
                try:
                    db.rename_folder(fid, new_name)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        if st.checkbox("이 폴더를 삭제합니다 (기록·사진 함께 삭제)"):
            if st.button("삭제 실행", type="primary"):
                db.delete_folder(fid)
                st.success("삭제했습니다.")
                st.rerun()


# ------------------------------------------------------------------ router
PAGES = {
    "📷 사진 업로드 · OCR": page_upload,
    "🗂 폴더 · 경기 기록": page_folder,
    "📊 오늘 · 폴더 합계": page_summary,
    "🏆 전체 종합": page_overall,
    "⚙️ 설정 · 백업": page_settings,
}
with st.sidebar:
    st.markdown("## 🎯 딜량 기록소")
    st.caption("칼바람 내기 기록 · 사진 OCR")
    choice = st.radio("메뉴", list(PAGES), label_visibility="collapsed")
    st.divider()
    folders = db.list_folders()
    st.caption(f"폴더 {len(folders)}개 · 경기 {sum(f['games'] for f in folders)}판")
    st.caption("사진은 폴더에 저장되고, OCR 초안은 저장 전에 반드시 확인하세요.")

PAGES[choice]()
