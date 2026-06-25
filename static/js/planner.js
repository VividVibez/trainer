// Week Planner interactions. Server is the source of truth: assign / unassign /
// toggle POST then reload; done-ticks update optimistically and refresh the delta.

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

document.addEventListener("click", async (e) => {
  const t = e.target.closest("button");
  if (!t) return;

  // --- reveal / hide the day picker on a tray card ---
  if (t.classList.contains("assign-toggle")) {
    const aid = t.dataset.aid;
    const picker = document.getElementById(`picker-${aid}`);
    const open = !picker.hidden;
    // close any other open pickers first
    document.querySelectorAll(".day-picker").forEach((p) => (p.hidden = true));
    document.querySelectorAll(".assign-toggle").forEach((b) => {
      b.classList.remove("open"); b.textContent = "+ Day";
    });
    if (!open) {
      picker.hidden = false;
      t.classList.add("open");
      t.textContent = "Cancel";
    }
    return;
  }

  // --- pick a day -> assign, then reload ---
  if (t.classList.contains("day-pick")) {
    try {
      await postJSON(`/api/assignment/${t.dataset.aid}/day`, { day_index: Number(t.dataset.day) });
      location.reload();
    } catch (err) { flashError(t); }
    return;
  }

  // --- unassign a placed card -> back to tray ---
  if (t.classList.contains("unassign")) {
    try {
      await postJSON(`/api/assignment/${t.dataset.aid}/unassign`);
      location.reload();
    } catch (err) { flashError(t); }
    return;
  }

  // --- tick done (optimistic + live delta) ---
  if (t.classList.contains("tick")) {
    const card = t.closest(".scard");
    const nowDone = !t.classList.contains("on");
    t.classList.toggle("on", nowDone);
    card.classList.toggle("done", nowDone);
    try {
      const data = await postJSON(`/api/assignment/${t.dataset.aid}/done`, { done: nowDone });
      if (data.delta) updateDelta(data.delta);
    } catch (err) {
      // revert on failure
      t.classList.toggle("on", !nowDone);
      card.classList.toggle("done", !nowDone);
      flashError(t);
    }
    return;
  }

  // --- 3 / 4 session toggle -> set + reload ---
  if (t.classList.contains("tg")) {
    if (t.classList.contains("on")) return;            // no change
    const week = t.closest(".toggle").dataset.week;
    try {
      await postJSON(`/api/week/${week}/toggle`, { sessions: Number(t.dataset.n) });
      location.reload();
    } catch (err) { flashError(t); }
    return;
  }
});

function updateDelta(delta) {
  const el = document.getElementById("delta");
  if (!el) return;
  el.classList.remove("ahead", "behind", "level");
  if (delta.value > 0) { el.classList.add("ahead"); el.textContent = `${delta.value} ahead`; }
  else if (delta.value < 0) { el.classList.add("behind"); el.textContent = `${-delta.value} behind`; }
  else { el.classList.add("level"); el.textContent = "On track"; }
}

function flashError(el) {
  const card = el.closest(".scard") || el;
  card.animate(
    [{ outline: "2px solid #F87171" }, { outline: "2px solid transparent" }],
    { duration: 700 }
  );
}
