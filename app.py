import streamlit as st

from guard.service import analyze_and_format


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="AI GUARD",
    page_icon="🛡️",
    layout="centered",
)


# ============================================================
# HEADER
# ============================================================

st.title("🛡️ AI GUARD")

st.caption(
    "AI-система раннего обнаружения мошенничества"
)


# ============================================================
# STATUS
# ============================================================

st.success(
    "🟢 GUARD CORE активен"
)

st.divider()


# ============================================================
# REQUEST LIMIT
# ============================================================

MAX_REQUESTS = 10

if "request_count" not in st.session_state:
    st.session_state.request_count = 0

st.caption(
    f"Запросов использовано: "
    f"{st.session_state.request_count}/{MAX_REQUESTS}"
)


# ============================================================
# INPUT
# ============================================================

st.subheader("Проверка ситуации")

text = st.text_area(
    "Опишите ситуацию",
    placeholder=(
        "Например:\n\n"
        "Мне позвонили якобы из банка и попросили "
        "срочно назвать код из SMS..."
    ),
    height=180,
)


# ============================================================
# ANALYZE BUTTON
# ============================================================

if st.button(
    "🔍 Анализировать",
    type="primary",
    use_container_width=True,
):

    if not text.strip():

        st.warning(
            "Сначала опишите ситуацию."
        )

    else:

        if st.session_state.request_count >= MAX_REQUESTS:

            st.warning(
                "Лимит запросов на эту сессию исчерпан."
            )

            st.stop()

        with st.spinner(
            "🧠 GUARD анализирует..."
        ):

            try:

                result = analyze_and_format(
                    text.strip()
                )

                st.session_state.request_count += 1

                st.divider()

                st.subheader(
                    "Результат анализа"
                )

                st.markdown(
                    result
                )

            except Exception as exc:

                st.error(
                    "Не удалось выполнить анализ."
                )

                st.code(
                    str(exc)
                )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "AI GUARD • MVP"
)