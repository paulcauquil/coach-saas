import os
import json
import bcrypt
import stripe
from datetime import datetime
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash)
from dotenv import load_dotenv
from supabase import create_client, Client
from functools import wraps
try:
    from flask_mail import Mail, Message as MailMessage
    _MAIL_AVAILABLE = True
except ImportError:
    _MAIL_AVAILABLE = False

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

# ── Flask-Mail (Elite — envoi d'emails convocations) ──────────────────────────
app.config.update(
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.getenv("MAIL_USERNAME", ""),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", ""),
    MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER", "noreply@tactix.app"),
)
if _MAIL_AVAILABLE:
    mail = Mail(app)
app.jinja_env.globals["chr"] = chr

# ── Postes disponibles par sport ──────────────────────────────────────────────
POSTES_PAR_SPORT = {
    "Football": [
        "Gardien", "Défenseur droit", "Défenseur central", "Défenseur gauche",
        "Latéral droit", "Latéral gauche", "Milieu défensif", "Milieu central",
        "Milieu offensif", "Ailier droit", "Ailier gauche",
        "Avant-centre", "Attaquant de soutien",
    ],
    "Rugby": [
        "Pilier gauche", "Talonneur", "Pilier droit", "Deuxième ligne",
        "Flanker", "Numéro 8", "Demi de mêlée", "Demi d'ouverture",
        "Ailier gauche", "Premier centre", "Deuxième centre", "Ailier droit", "Arrière",
    ],
    "Handball": [
        "Gardien", "Ailier gauche", "Ailier droit", "Arrière gauche",
        "Arrière droit", "Demi-centre", "Pivot",
    ],
    "Basket": [
        "Meneur", "Arrière", "Ailier", "Ailier fort", "Pivot",
    ],
    "Volley-ball": [
        "Passeur", "Réceptionneur attaquant", "Pointu", "Central", "Libero",
    ],
    "Hockey sur glace": [
        "Gardien", "Défenseur gauche", "Défenseur droit",
        "Ailier gauche", "Centre", "Ailier droit",
    ],
    "Football américain": [
        "Quarterback", "Running back", "Wide receiver", "Tight end",
        "Offensive lineman", "Defensive lineman", "Linebacker",
        "Cornerback", "Safety", "Kicker", "Punter",
    ],
    "Water-polo": [
        "Gardien", "Ailier gauche", "Ailier droit",
        "Avant-centre", "Centre", "Demi gauche", "Demi droit",
    ],
}

_POSTE_CAT_MAP = {
    "Gardien": "gardien", "Défenseur droit": "défenseur",
    "Défenseur central": "défenseur", "Défenseur gauche": "défenseur",
    "Latéral droit": "défenseur", "Latéral gauche": "défenseur",
    "Milieu défensif": "milieu", "Milieu central": "milieu",
    "Milieu offensif": "milieu", "Ailier droit": "attaquant",
    "Ailier gauche": "attaquant", "Avant-centre": "attaquant",
    "Attaquant de soutien": "attaquant", "Pilier gauche": "défenseur",
    "Talonneur": "défenseur", "Pilier droit": "défenseur",
    "Deuxième ligne": "défenseur", "Flanker": "défenseur",
    "Numéro 8": "défenseur", "Demi de mêlée": "milieu",
    "Demi d'ouverture": "milieu", "Premier centre": "attaquant",
    "Deuxième centre": "attaquant", "Arrière": "défenseur",
    "Arrière gauche": "défenseur", "Arrière droit": "défenseur",
    "Demi-centre": "milieu", "Pivot": "attaquant",
    "Meneur": "milieu", "Ailier": "attaquant", "Ailier fort": "attaquant",
    "Passeur": "milieu", "Réceptionneur attaquant": "attaquant",
    "Pointu": "attaquant", "Central": "défenseur", "Libero": "défenseur",
    "Centre": "milieu", "Quarterback": "attaquant", "Running back": "attaquant",
    "Wide receiver": "attaquant", "Tight end": "attaquant",
    "Offensive lineman": "défenseur", "Defensive lineman": "défenseur",
    "Linebacker": "défenseur", "Cornerback": "défenseur", "Safety": "défenseur",
    "Kicker": "milieu", "Punter": "milieu",
    "Demi gauche": "milieu", "Demi droit": "milieu",
    # Anciens postes courts (rétrocompatibilité)
    "gardien": "gardien", "défenseur": "défenseur",
    "milieu": "milieu",   "attaquant": "attaquant",
}


def poste_categorie(poste):
    """Retourne la catégorie couleur (gardien/défenseur/milieu/attaquant) pour un poste."""
    if not poste:
        return "milieu"
    cat = _POSTE_CAT_MAP.get(poste)
    if cat:
        return cat
    p = poste.lower()
    if "gardien" in p:
        return "gardien"
    if any(k in p for k in ["défens", "latéral", "pilier", "talonneur", "lineman",
                              "linebacker", "cornerback", "safety", "libero",
                              "central", "flanker"]):
        return "défenseur"
    if any(k in p for k in ["milieu", "demi", "passeur", "meneur", "kicker",
                              "punter", "centre", "arrière"]):
        return "milieu"
    if any(k in p for k in ["attaquant", "ailier", "avant", "pivot", "pointu",
                              "quarterback", "receiver", "running"]):
        return "attaquant"
    return "milieu"


app.jinja_env.globals["poste_categorie"] = poste_categorie

# ── Points par résultat selon le sport ───────────────────────────────────────
SPORT_POINTS = {
    "Football":           {"w": 3, "d": 1, "l": 0, "rugby_bonus": False},
    "Rugby":              {"w": 4, "d": 2, "l": 0, "rugby_bonus": True},
    "Basket":             {"w": 2, "d": 0, "l": 1, "rugby_bonus": False},
    "Handball":           {"w": 3, "d": 1, "l": 0, "rugby_bonus": False},
    "Volley-ball":        {"w": 3, "d": 2, "l": 1, "rugby_bonus": False},
    "Hockey sur glace":   {"w": 3, "d": 1, "l": 0, "rugby_bonus": False},
    "Football américain": {"w": 3, "d": 1, "l": 0, "rugby_bonus": False},
    "Water-polo":         {"w": 3, "d": 1, "l": 0, "rugby_bonus": False},
}


def _get_sport(club_id):
    """Récupère le sport du club depuis la DB."""
    row = supabase.table("clubs").select("sport").eq("id", club_id).single().execute().data or {}
    return row.get("sport", "Football") or "Football"


def get_or_create_equipe(club_id, nom_equipe, saison):
    """Retourne l'id de l'équipe dans classement, en la créant si absente."""
    res = supabase.table("classement").select("id")\
                  .eq("club_id", club_id).eq("nom_equipe", nom_equipe).eq("saison", saison)\
                  .execute()
    if res.data:
        return res.data[0]["id"]
    ins = supabase.table("classement").insert({
        "club_id": club_id, "nom_equipe": nom_equipe, "saison": saison,
        "matchs_joues": 0, "victoires": 0, "nuls": 0, "defaites": 0,
        "points_marques": 0, "points_encaisses": 0, "points_classement": 0,
    }).execute()
    return ins.data[0]["id"]


def _zero_stats():
    return {"matchs_joues": 0, "victoires": 0, "nuls": 0, "defaites": 0,
            "points_marques": 0, "points_encaisses": 0, "points_classement": 0}


def _accumulate(s, score_nous, score_eux, W, D, L, bonus=0):
    """Ajoute un résultat (du point de vue de l'équipe qui a marqué score_nous)."""
    s["matchs_joues"]     += 1
    s["points_marques"]   += score_nous
    s["points_encaisses"] += score_eux
    if score_nous > score_eux:
        s["victoires"] += 1
        s["points_classement"] += W + bonus
    elif score_nous == score_eux:
        s["nuls"] += 1
        s["points_classement"] += D + bonus
    else:
        s["defaites"] += 1
        s["points_classement"] += L + bonus


def sync_notre_equipe(club_id, nom_club, saison, sport):
    """Recalcule les stats de NOTRE équipe depuis deux sources :
    1. La table matchs (résultats ajoutés via /matchs)
    2. Les entrées source='manuel' de resultats_classement impliquant notre équipe
       (résultats saisis manuellement dans /classement avec notre équipe comme dom ou ext)
    Ne touche aucune autre équipe."""
    pts = SPORT_POINTS.get(sport, SPORT_POINTS["Football"])
    W, D, L = pts["w"], pts["d"], pts["l"]

    s = _zero_stats()

    # Source 1 : table matchs
    matchs_data = supabase.table("matchs").select("score_nous,score_eux")\
                          .eq("club_id", club_id).execute().data or []
    for m in matchs_data:
        sn, se = m.get("score_nous"), m.get("score_eux")
        if sn is None or se is None:
            continue
        _accumulate(s, sn, se, W, D, L)

    notre_id = get_or_create_equipe(club_id, nom_club, saison)

    # Source 2 : résultats manuels dans classement impliquant notre équipe
    try:
        manual = supabase.table("resultats_classement").select("*")\
                         .eq("club_id", club_id).eq("saison", saison)\
                         .eq("source", "manuel").execute().data or []
        for r in manual:
            did = r.get("equipe_dom_id")
            eid = r.get("equipe_ext_id")
            sd  = r.get("score_dom", 0) or 0
            se_r = r.get("score_ext", 0) or 0
            if did == notre_id:
                _accumulate(s, sd, se_r, W, D, L, int(r.get("bonus_dom") or 0))
            elif eid == notre_id:
                _accumulate(s, se_r, sd, W, D, L, int(r.get("bonus_ext") or 0))
    except Exception:
        pass  # Table absente — uniquement les matchs comptent

    supabase.table("classement").update(s).eq("id", notre_id).execute()
    return notre_id


def recalculate_classement(club_id, nom_club, saison, sport):
    """Recalcule les stats de TOUS LES ADVERSAIRES depuis deux sources :
    1. Table matchs : pour chaque match de notre équipe, l'adversaire reçoit le résultat inversé.
       On lit directement la table matchs (même source que sync_notre_equipe) pour éviter
       toute dépendance sur resultats_classement source='matchs'.
    2. resultats_classement source='manuel' : matchs entre autres équipes saisis à la main.
       Les entrées impliquant notre équipe y contribuent côté adversaire.
    Notre équipe est TOUJOURS exclue (ses stats viennent de sync_notre_equipe)."""
    pts = SPORT_POINTS.get(sport, SPORT_POINTS["Football"])
    W, D, L = pts["w"], pts["d"], pts["l"]

    notre_id = get_or_create_equipe(club_id, nom_club, saison)
    opp_stats = {}  # {adv_id: stats_dict}

    # ── Source 1 : adversaires de nos propres matchs (table matchs) ──────────
    matchs_data = supabase.table("matchs")\
                          .select("adversaire,score_nous,score_eux")\
                          .eq("club_id", club_id).execute().data or []
    for m in matchs_data:
        adv_name = (m.get("adversaire") or "").strip()
        sn = m.get("score_nous")
        se = m.get("score_eux")
        if not adv_name or sn is None or se is None:
            continue
        adv_id = get_or_create_equipe(club_id, adv_name, saison)
        if adv_id == notre_id:
            continue
        if adv_id not in opp_stats:
            opp_stats[adv_id] = _zero_stats()
        # Du point de vue de l'adversaire : ils ont marqué se, nous avons marqué sn
        _accumulate(opp_stats[adv_id], se, sn, W, D, L)

    # ── Source 2 : résultats manuels (resultats_classement source='manuel') ──
    try:
        manual = supabase.table("resultats_classement").select("*")\
                         .eq("club_id", club_id).eq("saison", saison)\
                         .eq("source", "manuel").execute().data or []
        for r in manual:
            did  = r.get("equipe_dom_id")
            eid  = r.get("equipe_ext_id")
            sd   = r.get("score_dom", 0) or 0
            se_r = r.get("score_ext", 0) or 0
            bd   = int(r.get("bonus_dom") or 0)
            be   = int(r.get("bonus_ext") or 0)
            # Équipe dom (si ce n'est pas nous)
            if did and did != notre_id:
                if did not in opp_stats:
                    opp_stats[did] = _zero_stats()
                _accumulate(opp_stats[did], sd, se_r, W, D, L, bd)
            # Équipe ext (si ce n'est pas nous)
            if eid and eid != notre_id:
                if eid not in opp_stats:
                    opp_stats[eid] = _zero_stats()
                _accumulate(opp_stats[eid], se_r, sd, W, D, L, be)
    except Exception:
        pass  # Table absente — seuls les matchs comptent pour les adversaires

    if not opp_stats:
        return

    zero = _zero_stats()
    for tid in opp_stats:
        supabase.table("classement").update(dict(zero)).eq("id", tid).execute()
    for tid, s in opp_stats.items():
        supabase.table("classement").update(s).eq("id", tid).execute()


def sync_match_to_classement(club_id, nom_club, match_id, adversaire,
                              score_nous, score_eux, domicile, date_match, sport):
    """Synchronisation complète après ajout/modif d'un match :
    1. Met à jour notre entrée dans resultats_classement (côté adversaire)
    2. Met à jour nos stats depuis tous les matchs (sync_notre_equipe)
    3. Recalcule les stats de tous les adversaires (recalculate_classement)
    """
    saison = (date_match[:4] if date_match else None) or str(datetime.now().year)
    mid_str = str(match_id)

    if score_nous is None or score_eux is None:
        # Pas encore de score : supprimer l'éventuelle entrée liée
        try:
            supabase.table("resultats_classement").delete()\
                    .eq("match_id", mid_str).eq("club_id", club_id).execute()
        except Exception:
            pass
    else:
        notre_id = get_or_create_equipe(club_id, nom_club, saison)
        adv_id   = get_or_create_equipe(club_id, adversaire, saison)
        # Orientation dom/ext
        if domicile:
            dom_id, ext_id = notre_id, adv_id
            score_dom, score_ext = score_nous, score_eux
        else:
            dom_id, ext_id = adv_id, notre_id
            score_dom, score_ext = score_eux, score_nous

        payload = {
            "club_id": club_id, "saison": saison,
            "equipe_dom_id": dom_id, "equipe_ext_id": ext_id,
            "score_dom": score_dom, "score_ext": score_ext,
            "bonus_dom": 0, "bonus_ext": 0,
            "source": "matchs", "match_id": mid_str,
        }
        try:
            existing = supabase.table("resultats_classement").select("id")\
                               .eq("match_id", mid_str).eq("club_id", club_id).execute()
            if existing.data:
                supabase.table("resultats_classement").update(payload)\
                        .eq("id", existing.data[0]["id"]).execute()
            else:
                supabase.table("resultats_classement").insert(payload).execute()
        except Exception:
            pass  # Table absente : la sync adversaire est silencieuse

    # Toujours mettre à jour nos stats (depuis matchs) + recalculer adversaires
    sync_notre_equipe(club_id, nom_club, saison, sport)
    try:
        recalculate_classement(club_id, nom_club, saison, sport)
    except Exception:
        pass


# ── Vocabulaire des scores par sport ──────────────────────────────────────────
SPORT_VOCAB = {
    "Football":           {"score_label": "Buts",   "nous": "Nos buts",   "eux": "Buts adv.",    "marqueurs": "Buteurs",             "detail": None},
    "Rugby":              {"score_label": "Points", "nous": "Nos points", "eux": "Points adv.",  "marqueurs": "Marqueurs",           "detail": "rugby"},
    "Basket":             {"score_label": "Points", "nous": "Nos points", "eux": "Points adv.",  "marqueurs": "Meilleurs marqueurs", "detail": None},
    "Handball":           {"score_label": "Buts",   "nous": "Nos buts",   "eux": "Buts adv.",    "marqueurs": "Buteurs",             "detail": None},
    "Volley-ball":        {"score_label": "Sets",   "nous": "Nos sets",   "eux": "Sets adv.",    "marqueurs": None,                  "detail": "volley"},
    "Hockey sur glace":   {"score_label": "Buts",   "nous": "Nos buts",   "eux": "Buts adv.",    "marqueurs": "Buteurs",             "detail": None},
    "Football américain": {"score_label": "Points", "nous": "Nos points", "eux": "Points adv.",  "marqueurs": "Marqueurs",           "detail": "amfoot"},
    "Water-polo":         {"score_label": "Buts",   "nous": "Nos buts",   "eux": "Buts adv.",    "marqueurs": "Buteurs",             "detail": None},
}

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


# ── Context processor : injecte logo + couleurs du club dans tous les templates
@app.context_processor
def inject_club_settings():
    nom = session.get("nom_club") or ""
    initiales = "".join(w[0] for w in nom.split()[:2]).upper() if nom else "?"
    return {
        "club_logo":      session.get("logo_url"),
        "club_c1":        session.get("couleur_principale", "#E24B4A"),
        "club_c2":        session.get("couleur_secondaire", "#378ADD"),
        "club_initiales": initiales,
        "user_role":      session.get("role", "president"),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Décorateurs
# ══════════════════════════════════════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "club_id" not in session:
            return redirect(url_for("connexion"))
        return f(*args, **kwargs)
    return decorated


def president_required(f):
    """Accessible au président uniquement."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "club_id" not in session:
            return redirect(url_for("connexion"))
        if session.get("role", "president") != "president":
            flash("Accès réservé au président du club.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def coach_or_president(f):
    """Accessible au coach et au président, pas aux joueurs."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "club_id" not in session:
            return redirect(url_for("connexion"))
        if session.get("role", "president") == "joueur":
            flash("Accès en lecture seule pour les joueurs.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def pro_required(f):
    """Redirige vers /tarifs si le club n'est pas au moins Pro."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("plan", "gratuit") not in ("pro", "elite"):
            flash("🔒 Fonctionnalité réservée au plan Pro.", "error")
            return redirect(url_for("tarifs"))
        return f(*args, **kwargs)
    return decorated


def elite_required(f):
    """Redirige vers /tarifs si le club n'est pas Elite."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("plan", "gratuit") != "elite":
            flash("🚀 Fonctionnalité réservée au plan Elite. Passez à Elite pour débloquer les analytics avancés, l'email automatique et plus.", "error")
            return redirect(url_for("tarifs"))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

@app.template_filter("format_month")
def format_month(s):
    mois = ["Janvier","Février","Mars","Avril","Mai","Juin",
            "Juillet","Août","Septembre","Octobre","Novembre","Décembre"]
    try:
        year, month = s.split("-")
        return f"{mois[int(month)-1]} {year}"
    except Exception:
        return s


def _auto_journal_entry(club_id, equipe_id, date_entree, titre, contenu,
                        categorie, source, source_id=None):
    """Crée une entrée automatique dans le journal (idempotent sur source_id)."""
    try:
        if source_id:
            ex = supabase.table("journal").select("id")\
                         .eq("club_id", club_id)\
                         .eq("source", source)\
                         .eq("source_id", str(source_id)).execute()
            if ex.data:
                return
        saison = (date_entree[:4] if date_entree else None) or str(datetime.now().year)
        row = {
            "club_id":     club_id,
            "date_entree": date_entree,
            "titre":       titre,
            "contenu":     contenu or "",
            "categorie":   categorie,
            "source":      source,
            "saison":      saison,
        }
        if equipe_id:
            row["equipe_id"] = str(equipe_id)
        if source_id:
            row["source_id"] = str(source_id)
        supabase.table("journal").insert(row).execute()
    except Exception:
        pass


def refresh_plan_in_session(club_id):
    """Relit le plan depuis Supabase et met à jour la session."""
    res = supabase.table("clubs").select("plan,stripe_customer_id").eq("id", club_id).execute()
    if res.data:
        session["plan"] = res.data[0].get("plan", "gratuit")
        session["stripe_customer_id"] = res.data[0].get("stripe_customer_id")


# ══════════════════════════════════════════════════════════════════════════════
#  Routes publiques
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if "club_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/tarifs")
def tarifs():
    if "club_id" in session and session.get("role") == "joueur":
        flash("Accès non autorisé.", "error")
        return redirect(url_for("dashboard"))
    plan = session.get("plan", "gratuit") if "club_id" in session else None
    return render_template("tarifs.html", plan=plan)


# ── Inscription ───────────────────────────────────────────────────────────────

@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if request.method == "POST":
        nom_club = request.form.get("nom_club", "").strip()
        email    = request.form.get("email", "").strip().lower()
        mdp      = request.form.get("mot_de_passe", "")
        ville    = request.form.get("ville", "").strip()
        sport    = request.form.get("sport", "")

        if not all([nom_club, email, mdp, ville, sport]):
            flash("Tous les champs sont obligatoires.", "error")
            return render_template("inscription.html")

        existing = supabase.table("clubs").select("id").eq("email", email).execute()
        if existing.data:
            flash("Un club avec cet email existe déjà.", "error")
            return render_template("inscription.html")

        hashed = bcrypt.hashpw(mdp.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        result = supabase.table("clubs").insert({
            "nom_club": nom_club, "email": email,
            "mot_de_passe": hashed, "ville": ville,
            "sport": sport, "plan": "gratuit",
        }).execute()

        if result.data:
            flash("Compte créé avec succès. Connectez-vous.", "success")
            return redirect(url_for("connexion"))
        flash("Erreur lors de la création du compte.", "error")

    return render_template("inscription.html")


# ── Connexion ─────────────────────────────────────────────────────────────────

@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if "club_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        mdp   = request.form.get("mot_de_passe", "")

        # ── Chercher d'abord dans clubs (président) ─────────────────
        result = supabase.table("clubs").select("*").eq("email", email).execute()
        if result.data:
            club = result.data[0]
            if bcrypt.checkpw(mdp.encode("utf-8"), club["mot_de_passe"].encode("utf-8")):
                session["club_id"]            = club["id"]
                session["nom_club"]           = club["nom_club"]
                session["role"]               = "president"
                session["plan"]               = club.get("plan", "gratuit")
                session["stripe_customer_id"] = club.get("stripe_customer_id")
                session["logo_url"]           = club.get("logo_url")
                session["couleur_principale"] = club.get("couleur_principale", "#E24B4A")
                session["couleur_secondaire"] = club.get("couleur_secondaire", "#378ADD")
                return redirect(url_for("dashboard"))

        # ── Chercher dans membres (coach / joueur) ──────────────────
        m_res = supabase.table("membres").select("*").eq("email", email).execute()
        if m_res.data:
            m = m_res.data[0]
            if bcrypt.checkpw(mdp.encode("utf-8"), m["mot_de_passe"].encode("utf-8")):
                # Récupérer infos du club
                club_res = supabase.table("clubs").select("*").eq("id", m["club_id"]).execute()
                club = club_res.data[0] if club_res.data else {}
                session["club_id"]            = m["club_id"]
                session["membre_id"]          = m["id"]
                session["equipe_id"]          = m.get("equipe_id")
                session["role"]               = m["role"]
                session["nom_club"]           = club.get("nom_club", "")
                session["nom_membre"]         = f"{m.get('prenom','')} {m.get('nom','')}".strip()
                session["plan"]               = club.get("plan", "gratuit")
                session["logo_url"]           = club.get("logo_url")
                session["couleur_principale"] = club.get("couleur_principale", "#E24B4A")
                session["couleur_secondaire"] = club.get("couleur_secondaire", "#378ADD")
                return redirect(url_for("dashboard"))

        flash("Email ou mot de passe incorrect.", "error")

    return render_template("connexion.html")


@app.route("/rejoindre", methods=["GET", "POST"])
def rejoindre():
    """Inscription via code d'invitation (coach ou joueur)."""
    code = request.args.get("code", "").strip().upper()
    if request.method == "GET":
        invitation = None
        equipe_info = None
        club_info = None
        error = None
        if code:
            try:
                inv_res = supabase.table("invitations").select("*").eq("code", code)\
                                  .eq("utilise", False).execute()
                if inv_res.data:
                    inv = inv_res.data[0]
                    # Vérifier expiration
                    exp = datetime.fromisoformat(inv["expires_at"].replace("Z", "+00:00"))
                    from datetime import timezone
                    if exp < datetime.now(timezone.utc):
                        error = "Ce code d'invitation a expiré."
                    else:
                        invitation = inv
                        eq_res = supabase.table("equipes_club").select("*")\
                                         .eq("id", inv["equipe_id"]).execute()
                        equipe_info = eq_res.data[0] if eq_res.data else {}
                        cl_res = supabase.table("clubs").select("nom_club,logo_url")\
                                         .eq("id", inv["club_id"]).execute()
                        club_info = cl_res.data[0] if cl_res.data else {}
                else:
                    error = "Code invalide ou déjà utilisé."
            except Exception as e:
                error = f"Erreur : {e}"
        return render_template("rejoindre.html", code=code, invitation=invitation,
                               equipe_info=equipe_info, club_info=club_info, error=error)

    # POST — créer le compte
    code       = request.form.get("code", "").strip().upper()
    email      = request.form.get("email", "").strip().lower()
    mdp        = request.form.get("mot_de_passe", "")
    prenom     = request.form.get("prenom", "").strip()
    nom        = request.form.get("nom", "").strip()

    if not all([code, email, mdp, prenom, nom]):
        flash("Tous les champs sont obligatoires.", "error")
        return redirect(url_for("rejoindre", code=code))

    try:
        from datetime import timezone
        inv_res = supabase.table("invitations").select("*").eq("code", code)\
                          .eq("utilise", False).execute()
        if not inv_res.data:
            flash("Code invalide ou déjà utilisé.", "error")
            return redirect(url_for("rejoindre", code=code))
        inv = inv_res.data[0]
        exp = datetime.fromisoformat(inv["expires_at"].replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            flash("Ce code d'invitation a expiré.", "error")
            return redirect(url_for("rejoindre", code=code))

        # Vérifier unicité email
        existing = supabase.table("membres").select("id").eq("email", email).execute()
        if existing.data:
            flash("Un compte existe déjà avec cet email.", "error")
            return redirect(url_for("rejoindre", code=code))
        # Vérifier aussi dans clubs
        existing2 = supabase.table("clubs").select("id").eq("email", email).execute()
        if existing2.data:
            flash("Un compte existe déjà avec cet email.", "error")
            return redirect(url_for("rejoindre", code=code))

        hashed = bcrypt.hashpw(mdp.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        supabase.table("membres").insert({
            "club_id":      inv["club_id"],
            "equipe_id":    inv["equipe_id"],
            "email":        email,
            "mot_de_passe": hashed,
            "prenom":       prenom,
            "nom":          nom,
            "role":         inv["role_cible"],
        }).execute()

        # Marquer l'invitation utilisée
        supabase.table("invitations").update({"utilise": True}).eq("id", inv["id"]).execute()

        flash("Compte créé avec succès. Connectez-vous.", "success")
        return redirect(url_for("connexion"))
    except Exception as e:
        flash(f"Erreur : {e}", "error")
        return redirect(url_for("rejoindre", code=code))


# ══════════════════════════════════════════════════════════════════════════════
#  Gestion des équipes (Président)
# ══════════════════════════════════════════════════════════════════════════════

import random, string

def _generate_code(club_nom, equipe_nom):
    """Génère un code d'invitation lisible : ABC-XYZ-XXXX"""
    initials = "".join(w[0] for w in (club_nom + " " + equipe_nom).upper().split()[:3])
    suffix   = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{initials}-{suffix}"


@app.route("/equipes")
@president_required
def gestion_equipes():
    club_id = session.get("club_id")
    try:
        eq_res = supabase.table("equipes_club").select("*")\
                         .eq("club_id", club_id).order("created_at").execute()
        equipes = eq_res.data or []
    except Exception:
        equipes = []
    # Charger les invitations actives
    try:
        from datetime import timezone
        inv_res = supabase.table("invitations").select("*")\
                          .eq("club_id", club_id)\
                          .eq("utilise", False).execute()
        invitations = [i for i in (inv_res.data or [])
                       if datetime.fromisoformat(i["expires_at"].replace("Z","+00:00"))
                          > datetime.now(timezone.utc)]
    except Exception:
        invitations = []
    # Charger les membres
    try:
        mb_res = supabase.table("membres").select("*").eq("club_id", club_id).execute()
        membres = mb_res.data or []
    except Exception:
        membres = []
    club = supabase.table("clubs").select("nom_club,sport").eq("id", club_id).execute().data or [{}]
    sport = club[0].get("sport", "Football")
    nom_club = club[0].get("nom_club", "")
    return render_template("equipes.html", equipes=equipes, invitations=invitations,
                           membres=membres, sport=sport, nom_club=nom_club)


@app.route("/equipes/ajouter", methods=["POST"])
@president_required
def ajouter_equipe_club():
    club_id    = session.get("club_id")
    nom_equipe = request.form.get("nom_equipe", "").strip()
    sport      = request.form.get("sport", "").strip()
    categorie  = request.form.get("categorie", "Seniors").strip()
    if not nom_equipe or not sport:
        flash("Nom et sport obligatoires.", "error")
        return redirect(url_for("gestion_equipes"))
    # Limite par plan
    plan_actuel = session.get("plan", "gratuit")
    if plan_actuel != "elite":
        limite = 1 if plan_actuel == "gratuit" else 3
        try:
            count_res = supabase.table("equipes_club").select("id").eq("club_id", club_id).execute()
            nb_equipes = len(count_res.data or [])
        except Exception:
            nb_equipes = 0
        if nb_equipes >= limite:
            plan_suivant = "Pro" if plan_actuel == "gratuit" else "Elite"
            flash(f"🔒 Limite atteinte ({limite} équipe{'s' if limite > 1 else ''} max sur votre plan). Passez au plan {plan_suivant} pour en créer davantage.", "error")
            return redirect(url_for("gestion_equipes"))
    try:
        res = supabase.table("equipes_club").insert({
            "club_id": club_id, "nom_equipe": nom_equipe,
            "sport": sport, "categorie": categorie,
        }).execute()
        # Créer automatiquement les 3 canaux de messagerie
        if res.data:
            _ensure_equipe_channels(club_id, res.data[0]["id"])
        flash(f"Équipe '{nom_equipe}' créée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("gestion_equipes"))


@app.route("/equipes/supprimer/<equipe_id>", methods=["POST"])
@president_required
def supprimer_equipe_club(equipe_id):
    club_id = session.get("club_id")
    try:
        supabase.table("equipes_club").delete()\
                .eq("id", equipe_id).eq("club_id", club_id).execute()
        flash("Équipe supprimée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("gestion_equipes"))


@app.route("/equipes/invitation/generer", methods=["POST"])
@president_required
def generer_invitation():
    club_id    = session.get("club_id")
    nom_club   = session.get("nom_club", "CLUB")
    equipe_id  = request.form.get("equipe_id", "").strip()
    role_cible = request.form.get("role_cible", "joueur")
    if not equipe_id:
        flash("Sélectionnez une équipe.", "error")
        return redirect(url_for("gestion_equipes"))
    try:
        eq_res = supabase.table("equipes_club").select("nom_equipe")\
                         .eq("id", equipe_id).execute()
        nom_equipe = eq_res.data[0]["nom_equipe"] if eq_res.data else "EQ"
        code = _generate_code(nom_club, nom_equipe)
        from datetime import timedelta, timezone
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        supabase.table("invitations").insert({
            "club_id": club_id, "equipe_id": equipe_id,
            "code": code, "role_cible": role_cible,
            "expires_at": expires.isoformat(),
        }).execute()
        flash(f"Code généré : {code} (valable 7 jours)", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("gestion_equipes"))


@app.route("/equipes/membre/supprimer/<membre_id>", methods=["POST"])
@president_required
def supprimer_membre(membre_id):
    club_id = session.get("club_id")
    try:
        supabase.table("membres").delete()\
                .eq("id", membre_id).eq("club_id", club_id).execute()
        flash("Membre supprimé.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("gestion_equipes"))


# ══════════════════════════════════════════════════════════════════════════════
#  Dashboard
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    club_id = session.get("club_id")

    # Rafraîchit le plan depuis la DB (important après retour du portail Stripe)
    refresh_plan_in_session(club_id)
    plan = session.get("plan", "gratuit")

    # Récupère le sport du club
    club_res = supabase.table("clubs").select("sport").eq("id", club_id).execute()
    sport = club_res.data[0].get("sport", "") if club_res.data else ""

    # Statistiques de saison
    matchs_result = supabase.table("matchs").select("*").eq("club_id", club_id).order("date_match", desc=True).execute()
    all_matchs = matchs_result.data or []
    stats = {"victoires": 0, "nuls": 0, "defaites": 0,
             "buts_marques": 0, "buts_encaisses": 0, "total": 0}
    for m in all_matchs:
        sn, se = m.get("score_nous"), m.get("score_eux")
        if sn is not None and se is not None:
            stats["total"] += 1
            stats["buts_marques"]  += sn
            stats["buts_encaisses"] += se
            if sn > se:   stats["victoires"] += 1
            elif sn == se: stats["nuls"]     += 1
            else:          stats["defaites"] += 1

    # Derniers matchs (5 max)
    recent_matchs = []
    for m in all_matchs[:5]:
        sn, se = m.get("score_nous"), m.get("score_eux")
        if sn is not None and se is not None:
            if sn > se:   result = "V"
            elif sn == se: result = "N"
            else:          result = "D"
        else:
            result = None
        recent_matchs.append({**m, "result": result})

    # Nombre de joueurs
    try:
        nb_joueurs = len(supabase.table("joueurs").select("id").eq("club_id", club_id).execute().data or [])
    except Exception:
        nb_joueurs = 0

    # Prochain adversaire (prochain match non encore joué)
    try:
        from datetime import date as _date
        today_str = str(_date.today())
        prochain_res = supabase.table("matchs").select("adversaire,date_match,domicile")\
            .eq("club_id", club_id).gte("date_match", today_str)\
            .is_("score_nous", "null")\
            .order("date_match").limit(1).execute()
        prochain_match = prochain_res.data[0] if prochain_res.data else None
    except Exception:
        prochain_match = None

    # Classement : position + mini-tableau
    position_classement = None
    mini_classement = []
    try:
        eq_res = supabase.table("classement").select("*").eq("club_id", club_id).execute()
        nom_club = session.get("nom_club", "")
        equipes_tri = sorted(eq_res.data or [], key=lambda e: (
            -(e.get("points_classement") or 0),
            -((e.get("points_marques") or 0) - (e.get("points_encaisses") or 0))
        ))
        # Trouver notre position (correspondance insensible à la casse)
        notre_idx = next(
            (i for i, e in enumerate(equipes_tri)
             if e.get("nom_equipe", "").strip().lower() == nom_club.strip().lower()),
            None
        )
        if notre_idx is not None:
            position_classement = notre_idx + 1
            total = len(equipes_tri)
            debut = max(0, notre_idx - 2)
            fin   = min(total, notre_idx + 3)
            # Ajustement si on est en tête ou en bas
            if debut == 0:
                fin = min(total, 5)
            elif fin == total:
                debut = max(0, total - 5)
            mini_classement = [
                {**e, "position": i + 1, "is_nous": i == notre_idx}
                for i, e in enumerate(equipes_tri)
            ][debut:fin]
    except Exception:
        pass

    # Meilleurs marqueurs (top 3)
    STAT_OFFENSIF = {
        "Football": ("buts", "but", "buts"),
        "Rugby": ("essais", "essai", "essais"),
        "Handball": ("buts", "but", "buts"),
        "Basket": ("points", "point", "points"),
        "Volley-ball": ("points_marques", "point", "points"),
        "Hockey sur glace": ("buts", "but", "buts"),
        "Football américain": ("touchdowns", "touchdown", "touchdowns"),
        "Water-polo": ("buts", "but", "buts"),
    }
    top_marqueurs = []
    try:
        stat_key, stat_sing, stat_plur = STAT_OFFENSIF.get(sport, ("buts", "but", "buts"))
        sj_res = supabase.table("stats_joueurs").select("joueur_id,stats")\
            .eq("club_id", club_id).execute()
        totaux = {}
        for row in (sj_res.data or []):
            jid = str(row.get("joueur_id", ""))
            val = int((row.get("stats") or {}).get(stat_key) or 0)
            totaux[jid] = totaux.get(jid, 0) + val
        top3_ids = sorted(totaux, key=lambda x: -totaux[x])[:3]
        top3_ids = [jid for jid in top3_ids if totaux[jid] > 0]
        if top3_ids:
            joueurs_res = supabase.table("joueurs").select("id,nom,prenom")\
                .in_("id", top3_ids).execute()
            joueurs_map = {str(j["id"]): j for j in (joueurs_res.data or [])}
            for jid in top3_ids:
                j = joueurs_map.get(jid, {})
                nb = totaux[jid]
                label = stat_plur if nb > 1 else stat_sing
                prenom = (j.get("prenom") or "")
                nom    = (j.get("nom") or "")
                initiales = (prenom[:1] + nom[:1]).upper() if (prenom or nom) else "?"
                top_marqueurs.append({
                    "nom": f"{prenom} {nom}".strip() or "Inconnu",
                    "initiales": initiales,
                    "nb": nb,
                    "label": label,
                })
    except Exception:
        pass

    vocab = SPORT_VOCAB.get(sport, SPORT_VOCAB["Football"])

    return render_template("dashboard.html",
                           nom_club=session.get("nom_club"),
                           plan=plan,
                           sport=sport,
                           vocab=vocab,
                           stats=stats,
                           nb_joueurs=nb_joueurs,
                           recent_matchs=recent_matchs,
                           prochain_match=prochain_match,
                           position_classement=position_classement,
                           mini_classement=mini_classement,
                           top_marqueurs=top_marqueurs)


# ══════════════════════════════════════════════════════════════════════════════
#  Effectif
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/effectif")
@login_required
def effectif():
    club_id  = session.get("club_id")
    result   = supabase.table("joueurs").select("*").eq("club_id", club_id).order("nom").execute()
    club_res = supabase.table("clubs").select("sport").eq("id", club_id).execute()
    sport    = club_res.data[0].get("sport", "Football") if club_res.data else "Football"
    postes   = POSTES_PAR_SPORT.get(sport, POSTES_PAR_SPORT["Football"])
    indispos = _fetch_indispos_actives(club_id)
    return render_template("effectif.html", joueurs=result.data, sport=sport,
                           postes=postes, indispos=indispos)


@app.route("/effectif/ajouter", methods=["POST"])
@coach_or_president
def ajouter_joueur():
    club_id = session.get("club_id")
    nom    = request.form.get("nom",    "").strip()
    prenom = request.form.get("prenom", "").strip()
    numero = request.form.get("numero", "").strip()
    poste  = request.form.get("poste",  "")
    dob    = request.form.get("date_naissance", "").strip() or None

    if not all([nom, prenom, poste]):
        flash("Nom, prénom et poste sont obligatoires.", "error")
        return redirect(url_for("effectif"))

    data = {"club_id": club_id, "nom": nom, "prenom": prenom, "poste": poste}
    if numero: data["numero"] = int(numero)
    if dob:    data["date_naissance"] = dob

    supabase.table("joueurs").insert(data).execute()
    flash(f"{prenom} {nom} ajouté à l'effectif.", "success")
    return redirect(url_for("effectif"))


@app.route("/effectif/modifier/<joueur_id>", methods=["POST"])
@coach_or_president
def modifier_joueur(joueur_id):
    club_id = session.get("club_id")
    if not supabase.table("joueurs").select("id").eq("id", joueur_id).eq("club_id", club_id).execute().data:
        flash("Joueur introuvable.", "error")
        return redirect(url_for("effectif"))

    nom    = request.form.get("nom",    "").strip()
    prenom = request.form.get("prenom", "").strip()
    numero = request.form.get("numero", "").strip()
    poste  = request.form.get("poste",  "")
    dob    = request.form.get("date_naissance", "").strip() or None

    data = {"nom": nom, "prenom": prenom, "poste": poste, "date_naissance": dob}
    if numero: data["numero"] = int(numero)

    supabase.table("joueurs").update(data).eq("id", joueur_id).eq("club_id", club_id).execute()
    flash(f"{prenom} {nom} modifié.", "success")
    return redirect(url_for("effectif"))


@app.route("/effectif/supprimer/<joueur_id>", methods=["POST"])
@coach_or_president
def supprimer_joueur(joueur_id):
    supabase.table("joueurs").delete().eq("id", joueur_id).eq("club_id", session.get("club_id")).execute()
    flash("Joueur supprimé de l'effectif.", "success")
    return redirect(url_for("effectif"))


# ══════════════════════════════════════════════════════════════════════════════
#  Profil joueur
# ══════════════════════════════════════════════════════════════════════════════

# Stats fields by sport
STATS_FIELDS = {
    "Football":           ["matchs_joues","buts","passes_decisives","cartons_jaunes","cartons_rouges","minutes_jouees"],
    "Rugby":              ["matchs_joues","essais","transformations","penalites","drops","plaquages","cartons"],
    "Handball":           ["matchs_joues","buts","passes_decisives","cartons"],
    "Basket":             ["matchs_joues","points","passes_decisives","rebonds"],
    "Volley-ball":        ["matchs_joues","points_marques","aces","blocs"],
    "Hockey sur glace":   ["matchs_joues","buts","passes_decisives","penalites"],
    "Football américain": ["matchs_joues","touchdowns","field_goals","plaquages"],
    "Water-polo":         ["matchs_joues","buts","passes_decisives","penalites"],
}
STATS_LABELS = {
    "matchs_joues": "Matchs",
    "buts": "Buts",
    "passes_decisives": "Passes déc.",
    "cartons_jaunes": "Jaunes",
    "cartons_rouges": "Rouges",
    "minutes_jouees": "Minutes",
    "essais": "Essais",
    "transformations": "Transfo.",
    "penalites": "Pénalités",
    "drops": "Drops",
    "plaquages": "Plaquages",
    "cartons": "Cartons",
    "points": "Points",
    "rebonds": "Rebonds",
    "points_marques": "Points",
    "aces": "Aces",
    "blocs": "Blocs",
    "touchdowns": "Touchdowns",
    "field_goals": "Field Goals",
}

# Stats capturable depuis les matchs (par sport)
INDISPO_TYPES   = ["Blessure", "Suspension", "Raison personnelle", "Maladie"]
INDISPO_GRAVITE = ["Légère", "Modérée", "Grave"]

def indispo_color(type_i, gravite):
    """Retourne la couleur hex selon type + gravité."""
    if type_i == "Blessure":
        if gravite == "Grave":   return "#f43f5e"
        if gravite == "Modérée": return "#f97316"
        return "#f59e0b"
    if type_i == "Suspension": return "#f59e0b"
    if type_i == "Maladie":    return "#a78bfa"
    return "#6b7280"

app.jinja_env.globals["indispo_color"] = indispo_color

JOURNAL_CATEGORIES = ["Entraînement", "Match", "Blessure", "Tactique", "Groupe", "Autre"]
JOURNAL_HUMEURS    = ["Excellent", "Bon", "Moyen", "Difficile"]
JOURNAL_CAT_COLORS = {
    "Entraînement": "#4f7cff",
    "Match":        "#22c55e",
    "Blessure":     "#f43f5e",
    "Tactique":     "#a78bfa",
    "Groupe":       "#f59e0b",
    "Autre":        "#6b7280",
}
JOURNAL_MOOD_EMOJI = {
    "Excellent": "😀", "Bon": "🙂", "Moyen": "😐", "Difficile": "😟"
}

MATCH_STATS_FIELDS = {
    "Football":           [("buts", "Buts"), ("passes_decisives", "Passes déc.")],
    "Rugby":              [("essais", "Essais"), ("transformations", "Transfo."), ("penalites", "Pénalités"), ("drops", "Drops")],
    "Handball":           [("buts", "Buts")],
    "Basket":             [("points", "Points"), ("passes_decisives", "Passes déc.")],
    "Volley-ball":        [("points_marques", "Points"), ("aces", "Aces"), ("blocs", "Blocs")],
    "Hockey sur glace":   [("buts", "Buts"), ("passes_decisives", "Passes")],
    "Football américain": [("touchdowns", "Touchdowns"), ("field_goals", "Field Goals")],
    "Water-polo":         [("buts", "Buts")],
}


def _build_marqueurs_from_stats(stats_list, joueurs_by_id, sport):
    """Génère la chaîne d'affichage des marqueurs depuis les stats structurées."""
    parts = []
    for entry in stats_list:
        jid = str(entry.get("joueur_id", ""))
        j = joueurs_by_id.get(jid, {})
        nom = f"{j.get('prenom', '')} {j.get('nom', '')}".strip() or "?"
        actions = []
        for field, label in MATCH_STATS_FIELDS.get(sport, []):
            val = int(entry.get(field) or 0)
            if val > 0:
                actions.append(f"{val} {label.lower()}")
        if actions:
            parts.append(f"{nom} ({', '.join(actions)})")
    return " · ".join(parts) if parts else None


def sync_compo_match(club_id, match_id, compo_list):
    """Remplace la composition du match (supprime puis réinsère)."""
    try:
        supabase.table("compositions_match").delete()\
                .eq("match_id", str(match_id)).eq("club_id", club_id).execute()
    except Exception:
        pass
    for entry in compo_list:
        joueur_id = entry.get("joueur_id")
        statut    = entry.get("statut", "titulaire")
        if not joueur_id or statut not in ("titulaire", "remplaçant"):
            continue
        try:
            supabase.table("compositions_match").insert({
                "club_id":   club_id,
                "match_id":  str(match_id),
                "joueur_id": joueur_id,
                "statut":    statut,
            }).execute()
        except Exception:
            pass


def sync_stats_joueurs(club_id, match_id, stats_list):
    """Remplace les stats_joueurs de ce match par les nouvelles données."""
    try:
        supabase.table("stats_joueurs").delete()\
                .eq("match_id", str(match_id)).eq("club_id", club_id).execute()
    except Exception:
        pass
    for entry in stats_list:
        joueur_id = entry.get("joueur_id")
        if not joueur_id:
            continue
        stats_data = {k: v for k, v in entry.items() if k != "joueur_id"}
        if not any(int(v or 0) > 0 for v in stats_data.values()):
            continue
        try:
            supabase.table("stats_joueurs").insert({
                "club_id": club_id,
                "joueur_id": joueur_id,
                "match_id": str(match_id),
                "stats": stats_data,
            }).execute()
        except Exception:
            pass


@app.route("/joueurs/<joueur_id>")
@login_required
def profil_joueur(joueur_id):
    club_id  = session.get("club_id")
    role     = session.get("role", "president")
    sport    = _get_sport(club_id)

    # Joueur
    try:
        jr = supabase.table("joueurs").select("*").eq("id", joueur_id).eq("club_id", club_id).execute()
        if not jr.data:
            flash("Joueur introuvable.", "error")
            return redirect(url_for("effectif"))
        joueur = jr.data[0]
    except Exception as e:
        flash(f"Erreur : {e}", "error")
        return redirect(url_for("effectif"))

    # Matchs du club (pour forme + historique)
    try:
        mr = supabase.table("matchs").select("id,date_match,adversaire,score_nous,score_eux,domicile")\
                     .eq("club_id", club_id).order("date_match", desc=True).execute()
        matchs = mr.data or []
    except Exception:
        matchs = []

    # Stats du joueur depuis stats_joueurs
    try:
        sr = supabase.table("stats_joueurs").select("match_id,stats")\
                     .eq("joueur_id", joueur_id).eq("club_id", club_id).execute()
        stats_rows = sr.data or []
    except Exception:
        stats_rows = []
    stats_by_match = {str(r["match_id"]): r["stats"] for r in stats_rows if r.get("match_id")}

    # Composition du joueur par match (titulaire / remplaçant)
    try:
        cr = supabase.table("compositions_match").select("match_id,statut")\
                     .eq("joueur_id", joueur_id).eq("club_id", club_id).execute()
        compo_rows = cr.data or []
    except Exception:
        compo_rows = []
    compo_by_match = {str(r["match_id"]): r["statut"] for r in compo_rows}

    # Stats cumulées (matchs_joues depuis compositions_match)
    fields = STATS_FIELDS.get(sport, STATS_FIELDS["Football"])
    stats_total = {f: 0 for f in fields}
    if "matchs_joues" in fields:
        stats_total["matchs_joues"] = len(compo_rows)
    for r in stats_rows:
        s = r.get("stats") or {}
        for f in fields:
            if f == "matchs_joues":
                continue
            stats_total[f] = stats_total.get(f, 0) + (int(s.get(f) or 0))

    # Absences
    try:
        ar = supabase.table("absences").select("*")\
                     .eq("joueur_id", joueur_id).eq("club_id", club_id)\
                     .order("date_abs", desc=True).execute()
        absences = ar.data or []
    except Exception:
        absences = []
    absences_match_ids = {str(a["match_id"]) for a in absences if a.get("match_id")}

    # Forme 5 derniers matchs
    forme = []
    for m in matchs[:5]:
        mid = str(m["id"])
        sn, se = m.get("score_nous"), m.get("score_eux")
        if mid in absences_match_ids:
            statut = "absent"
        elif mid in compo_by_match:
            if sn is None:
                statut = "absent"
            elif sn > se:
                statut = "victoire"
            elif sn == se:
                statut = "nul"
            else:
                statut = "defaite"
        else:
            statut = "absent"
        forme.append({"match": m, "statut": statut})

    # Historique matchs avec participation (depuis compositions_match)
    historique = []
    for m in matchs:
        mid = str(m["id"])
        if mid in compo_by_match:
            label = "Titulaire" if compo_by_match[mid] == "titulaire" else "Remplaçant"
        elif mid in absences_match_ids:
            label = "Absent"
        else:
            label = "—"
        historique.append({"match": m, "participation": label,
                           "stats": stats_by_match.get(mid, {})})

    stats_fields_labels = [(f, STATS_LABELS.get(f, f)) for f in fields]

    # Indisponibilités du joueur
    try:
        indr = supabase.table("indisponibilites").select("*")\
                       .eq("joueur_id", joueur_id).eq("club_id", club_id)\
                       .order("date_debut", desc=True).execute()
        indispos_joueur = indr.data or []
    except Exception:
        indispos_joueur = []

    indispo_active = next((i for i in indispos_joueur if i.get("actif")), None)

    return render_template("profil_joueur.html",
                           joueur=joueur, sport=sport,
                           forme=forme, matchs=matchs,
                           stats_total=stats_total,
                           stats_fields_labels=stats_fields_labels,
                           absences=absences,
                           historique=historique,
                           indispos_joueur=indispos_joueur,
                           indispo_active=indispo_active,
                           can_edit=(role != "joueur"),
                           stats_fields=fields)


@app.route("/joueurs/<joueur_id>/note-forme", methods=["POST"])
@coach_or_president
def update_note_forme(joueur_id):
    club_id = session.get("club_id")
    note = request.form.get("note_forme", "").strip()
    statut = request.form.get("statut_disponibilite", "").strip()
    data = {}
    if note and note.isdigit() and 1 <= int(note) <= 5:
        data["note_forme"] = int(note)
        data["note_forme_updated_at"] = datetime.now().isoformat()
    if statut in ("Disponible", "Blessé", "Suspendu"):
        data["statut_disponibilite"] = statut
    if data:
        try:
            supabase.table("joueurs").update(data).eq("id", joueur_id).eq("club_id", club_id).execute()
            flash("Profil mis à jour.", "success")
        except Exception as e:
            flash(f"Erreur : {e}", "error")
    return redirect(url_for("profil_joueur", joueur_id=joueur_id))


@app.route("/joueurs/<joueur_id>/absence/ajouter", methods=["POST"])
@coach_or_president
def ajouter_absence(joueur_id):
    club_id  = session.get("club_id")
    match_id = request.form.get("match_id") or None
    date_abs = request.form.get("date_abs") or None
    raison   = request.form.get("raison", "Non convoqué")
    notes    = request.form.get("notes", "").strip() or None
    try:
        supabase.table("absences").insert({
            "joueur_id": joueur_id, "club_id": club_id,
            "match_id": match_id, "date_abs": date_abs,
            "raison": raison, "notes": notes,
        }).execute()
        flash("Absence enregistrée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("profil_joueur", joueur_id=joueur_id))


@app.route("/joueurs/<joueur_id>/absence/supprimer/<absence_id>", methods=["POST"])
@coach_or_president
def supprimer_absence(joueur_id, absence_id):
    club_id = session.get("club_id")
    try:
        supabase.table("absences").delete()\
                .eq("id", absence_id).eq("club_id", club_id).execute()
        flash("Absence supprimée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("profil_joueur", joueur_id=joueur_id))


# ══════════════════════════════════════════════════════════════════════════════
#  Composition  (Pro uniquement)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/composition")
@login_required
@pro_required
def composition():
    club_id = session.get("club_id")
    result   = supabase.table("joueurs").select("*").eq("club_id", club_id).order("poste").execute()
    club_res = supabase.table("clubs").select("sport,couleur_principale,couleur_secondaire").eq("id", club_id).execute()
    club_row = club_res.data[0] if club_res.data else {}
    sport = club_row.get("sport", "Football") or "Football"
    c1    = club_row.get("couleur_principale") or session.get("couleur_principale", "#E24B4A")
    c2    = club_row.get("couleur_secondaire") or session.get("couleur_secondaire", "#378ADD")
    return render_template("composition.html",
                           joueurs=result.data or [],
                           nom_club=session.get("nom_club"),
                           sport=sport,
                           couleur_principale=c1,
                           couleur_secondaire=c2)


# ══════════════════════════════════════════════════════════════════════════════
#  Matchs
# ══════════════════════════════════════════════════════════════════════════════

@app.template_filter("format_date")
def format_date(value):
    if not value:
        return ""
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return value


@app.route("/matchs")
@login_required
def matchs():
    club_id  = session.get("club_id")
    club_row = (supabase.table("clubs").select("sport").eq("id", club_id).single().execute().data) or {}
    sport    = club_row.get("sport", "Football") or "Football"
    result   = supabase.table("matchs").select("*").eq("club_id", club_id).order("date_match", desc=True).execute()
    vocab    = SPORT_VOCAB.get(sport, SPORT_VOCAB["Football"])
    # Effectif pour le sélecteur de joueurs
    try:
        eff_res  = supabase.table("joueurs").select("id,prenom,nom,poste")\
                           .eq("club_id", club_id).order("nom").execute()
        effectif = eff_res.data or []
    except Exception:
        effectif = []
    # Stats existantes par match (pour pré-remplissage modal modifier)
    try:
        sj_res  = supabase.table("stats_joueurs").select("match_id,joueur_id,stats")\
                          .eq("club_id", club_id).execute()
        sj_rows = sj_res.data or []
    except Exception:
        sj_rows = []
    stats_by_match = {}
    for r in sj_rows:
        mid   = str(r["match_id"])
        entry = {"joueur_id": str(r["joueur_id"])}
        entry.update(r.get("stats") or {})
        stats_by_match.setdefault(mid, []).append(entry)
    match_stats_fields = MATCH_STATS_FIELDS.get(sport, [])
    # Compositions par match (pour pré-remplissage modal modifier)
    try:
        cm_res  = supabase.table("compositions_match").select("match_id,joueur_id,statut")\
                          .eq("club_id", club_id).execute()
        cm_rows = cm_res.data or []
    except Exception:
        cm_rows = []
    compos_by_match = {}
    for r in cm_rows:
        mid = str(r["match_id"])
        compos_by_match.setdefault(mid, []).append(
            {"joueur_id": str(r["joueur_id"]), "statut": r["statut"]}
        )
    return render_template("matchs.html",
                           matchs=result.data or [],
                           sport=sport, vocab=vocab,
                           effectif=effectif,
                           stats_by_match=stats_by_match,
                           match_stats_fields=match_stats_fields,
                           compos_by_match=compos_by_match)


@app.route("/matchs/ajouter", methods=["POST"])
@coach_or_president
def ajouter_match():
    club_id    = session.get("club_id")
    date_match = request.form.get("date_match",  "").strip()
    adversaire = request.form.get("adversaire",  "").strip()
    score_nous = request.form.get("score_nous",  "").strip()
    score_eux  = request.form.get("score_eux",   "").strip()
    domicile   = request.form.get("domicile", "false") == "true"
    notes      = request.form.get("notes",       "").strip() or None
    lien_video = request.form.get("lien_video",  "").strip() or None
    detail_n_raw      = request.form.get("detail_score_nous",  "").strip()
    detail_e_raw      = request.form.get("detail_score_eux",   "").strip()
    stats_joueurs_raw = request.form.get("stats_joueurs_json", "").strip()
    compo_raw         = request.form.get("compo_json",         "").strip()

    stats_list = []
    try:
        if stats_joueurs_raw:
            stats_list = json.loads(stats_joueurs_raw)
    except (ValueError, TypeError):
        pass
    compo_list = []
    try:
        if compo_raw:
            compo_list = json.loads(compo_raw)
    except (ValueError, TypeError):
        pass

    if not all([date_match, adversaire]):
        flash("La date et l'adversaire sont obligatoires.", "error")
        return redirect(url_for("matchs"))

    sport = _get_sport(club_id)

    # Génère la chaîne marqueurs depuis les stats structurées
    marqueurs = None
    if stats_list:
        try:
            eff   = supabase.table("joueurs").select("id,prenom,nom").eq("club_id", club_id).execute()
            jdict = {str(j["id"]): j for j in (eff.data or [])}
            marqueurs = _build_marqueurs_from_stats(stats_list, jdict, sport)
        except Exception:
            pass

    data = {"club_id": club_id, "date_match": date_match,
            "adversaire": adversaire, "domicile": domicile}
    if score_nous != "": data["score_nous"] = int(score_nous)
    if score_eux  != "": data["score_eux"]  = int(score_eux)
    if marqueurs:         data["marqueurs"]   = marqueurs
    if notes:             data["notes"]       = notes
    if lien_video:        data["lien_video"]  = lien_video
    try:
        if detail_n_raw: data["detail_score_nous"] = json.loads(detail_n_raw)
        if detail_e_raw: data["detail_score_eux"]  = json.loads(detail_e_raw)
    except (ValueError, TypeError):
        pass

    res = supabase.table("matchs").insert(data).execute()
    if res.data:
        match_id = res.data[0]["id"]
        sn_int = int(score_nous) if score_nous != "" else None
        se_int = int(score_eux)  if score_eux  != "" else None
        sync_match_to_classement(club_id, session.get("nom_club", ""),
                                 match_id, adversaire,
                                 sn_int, se_int, domicile, date_match, sport)
        if stats_list:
            sync_stats_joueurs(club_id, match_id, stats_list)
        sync_compo_match(club_id, match_id, compo_list)
        lieu_str  = "à domicile" if domicile else "à l'extérieur"
        score_str = f"{score_nous}-{score_eux}" if score_nous != "" and score_eux != "" else "score non saisi"
        _auto_journal_entry(
            club_id=club_id, equipe_id=session.get("equipe_id"),
            date_entree=date_match,
            titre=f"Match {lieu_str} — {adversaire}",
            contenu=f"Score : {score_str}." + (f"\n\n{notes}" if notes else ""),
            categorie="Match", source="match", source_id=match_id,
        )
    flash(f"Match contre {adversaire} ajouté.", "success")
    return redirect(url_for("matchs"))


@app.route("/matchs/modifier/<match_id>", methods=["POST"])
@coach_or_president
def modifier_match(match_id):
    club_id = session.get("club_id")
    if not supabase.table("matchs").select("id").eq("id", match_id).eq("club_id", club_id).execute().data:
        flash("Match introuvable.", "error")
        return redirect(url_for("matchs"))

    adversaire        = request.form.get("adversaire", "").strip()
    score_nous        = request.form.get("score_nous", "").strip()
    score_eux         = request.form.get("score_eux",  "").strip()
    detail_n_raw      = request.form.get("detail_score_nous",  "").strip()
    detail_e_raw      = request.form.get("detail_score_eux",   "").strip()
    stats_joueurs_raw = request.form.get("stats_joueurs_json", "").strip()
    compo_raw         = request.form.get("compo_json",         "").strip()

    stats_list = []
    try:
        if stats_joueurs_raw:
            stats_list = json.loads(stats_joueurs_raw)
    except (ValueError, TypeError):
        pass
    compo_list = []
    try:
        if compo_raw:
            compo_list = json.loads(compo_raw)
    except (ValueError, TypeError):
        pass

    sport = _get_sport(club_id)

    # Génère la chaîne marqueurs depuis les stats structurées
    marqueurs = None
    if stats_list:
        try:
            eff   = supabase.table("joueurs").select("id,prenom,nom").eq("club_id", club_id).execute()
            jdict = {str(j["id"]): j for j in (eff.data or [])}
            marqueurs = _build_marqueurs_from_stats(stats_list, jdict, sport)
        except Exception:
            pass

    data = {
        "date_match":  request.form.get("date_match", "").strip(),
        "adversaire":  adversaire,
        "domicile":    request.form.get("domicile", "false") == "true",
        "notes":       request.form.get("notes", "").strip() or None,
        "lien_video":  request.form.get("lien_video", "").strip() or None,
        "marqueurs":   marqueurs,
        "score_nous":  int(score_nous) if score_nous != "" else None,
        "score_eux":   int(score_eux)  if score_eux  != "" else None,
    }
    try:
        data["detail_score_nous"] = json.loads(detail_n_raw) if detail_n_raw else None
        data["detail_score_eux"]  = json.loads(detail_e_raw) if detail_e_raw else None
    except (ValueError, TypeError):
        pass
    supabase.table("matchs").update(data).eq("id", match_id).eq("club_id", club_id).execute()
    sync_match_to_classement(club_id, session.get("nom_club", ""),
                             match_id, adversaire,
                             data["score_nous"], data["score_eux"],
                             data["domicile"], data["date_match"], sport)
    sync_stats_joueurs(club_id, match_id, stats_list)
    sync_compo_match(club_id, match_id, compo_list)
    flash(f"Match contre {adversaire} modifié.", "success")
    return redirect(url_for("matchs"))


@app.route("/matchs/supprimer/<match_id>", methods=["POST"])
@coach_or_president
def supprimer_match(match_id):
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    saison   = str(datetime.now().year)
    sport    = _get_sport(club_id)
    # Supprimer convocations, composition et stats joueurs liées à ce match
    for tbl in ("convocations", "compositions_match", "stats_joueurs"):
        try:
            supabase.table(tbl).delete()\
                    .eq("match_id", str(match_id)).eq("club_id", club_id).execute()
        except Exception:
            pass
    # Supprimer l'entrée resultats_classement liée à ce match
    try:
        supabase.table("resultats_classement").delete()\
                .eq("match_id", str(match_id)).eq("club_id", club_id).execute()
    except Exception:
        pass
    supabase.table("matchs").delete().eq("id", match_id).eq("club_id", club_id).execute()
    # Resync notre équipe + adversaires
    sync_notre_equipe(club_id, nom_club, saison, sport)
    try:
        recalculate_classement(club_id, nom_club, saison, sport)
    except Exception:
        pass
    flash("Match supprimé.", "success")
    return redirect(url_for("matchs"))


# ══════════════════════════════════════════════════════════════════════════════
#  Convocations
# ══════════════════════════════════════════════════════════════════════════════

SPORT_EMOJIS = {
    "Football":           "⚽",
    "Rugby":              "🏉",
    "Basket":             "🏀",
    "Handball":           "🤾",
    "Volley-ball":        "🏐",
    "Hockey sur glace":   "🏒",
    "Football américain": "🏈",
    "Water-polo":         "🤽",
}


@app.route("/convocations/<match_id>", methods=["GET", "POST"])
@coach_or_president
def convocations(match_id):
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    sport    = _get_sport(club_id)

    mr = supabase.table("matchs").select("*").eq("id", match_id).eq("club_id", club_id).execute()
    if not mr.data:
        flash("Match introuvable.", "error")
        return redirect(url_for("matchs"))
    match = mr.data[0]

    if request.method == "POST":
        joueur_ids = request.form.getlist("joueur_ids")
        try:
            supabase.table("convocations").delete()\
                    .eq("match_id", match_id).eq("club_id", club_id).execute()
        except Exception:
            pass
        for jid in joueur_ids:
            statut = request.form.get(f"statut_{jid}", "non_precise")
            if statut not in ("titulaire_pressenti", "remplacant", "non_precise"):
                statut = "non_precise"
            try:
                supabase.table("convocations").insert({
                    "club_id":   club_id,
                    "match_id":  match_id,
                    "joueur_id": jid,
                    "statut":    statut,
                    "confirme":  False,
                }).execute()
            except Exception:
                pass
        flash("Convocations enregistrées.", "success")
        return redirect(url_for("convocations", match_id=match_id))

    try:
        eff_res  = supabase.table("joueurs").select("*")\
                           .eq("club_id", club_id).order("nom").execute()
        effectif = eff_res.data or []
    except Exception:
        effectif = []

    try:
        conv_res = supabase.table("convocations").select("joueur_id,statut,confirme")\
                           .eq("match_id", match_id).eq("club_id", club_id).execute()
        conv_rows = conv_res.data or []
    except Exception:
        conv_rows = []
    conv_by_joueur = {str(r["joueur_id"]): r for r in conv_rows}

    indispos = _fetch_indispos_actives(club_id)
    return render_template("convocations.html",
                           match=match,
                           effectif=effectif,
                           conv_by_joueur=conv_by_joueur,
                           indispos=indispos,
                           sport=sport,
                           nom_club=nom_club,
                           sport_emoji=SPORT_EMOJIS.get(sport, "⚽"))


# ══════════════════════════════════════════════════════════════════════════════
#  Classement
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/classement")
@login_required
def classement():
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    saison   = str(datetime.now().year)
    sport    = _get_sport(club_id)
    pts_rules = SPORT_POINTS.get(sport, SPORT_POINTS["Football"])

    # Équipes triées : points desc, puis différence desc
    eq_res  = supabase.table("classement").select("*").eq("club_id", club_id).execute()
    equipes = sorted(eq_res.data or [], key=lambda e: (
        -(e.get("points_classement") or 0),
        -((e.get("points_marques") or 0) - (e.get("points_encaisses") or 0))
    ))

    # Tous les résultats du club (toutes saisons), avec noms des équipes
    eq_by_id = {e["id"]: e["nom_equipe"] for e in equipes}
    try:
        res_res = supabase.table("resultats_classement").select("*")\
                          .eq("club_id", club_id)\
                          .order("created_at", desc=True).execute()
        resultats_raw = res_res.data or []
    except Exception:
        resultats_raw = []
    resultats = []
    for r in resultats_raw:
        r["nom_dom"] = eq_by_id.get(r.get("equipe_dom_id"), "?")
        r["nom_ext"] = eq_by_id.get(r.get("equipe_ext_id"), "?")
        resultats.append(r)

    return render_template("classement.html",
                           equipes=equipes,
                           nom_club=nom_club,
                           saison=saison,
                           sport=sport,
                           pts_rules=pts_rules,
                           resultats=resultats)


@app.route("/classement/ajouter", methods=["POST"])
@coach_or_president
def ajouter_equipe():
    club_id = session.get("club_id")
    nom     = request.form.get("nom_equipe", "").strip()
    saison  = request.form.get("saison", str(datetime.now().year))
    if not nom:
        flash("Le nom de l'équipe est obligatoire.", "error")
        return redirect(url_for("classement"))
    # Ne pas créer de doublon
    existing = supabase.table("classement").select("id")\
                       .eq("club_id", club_id).eq("nom_equipe", nom).eq("saison", saison).execute()
    if existing.data:
        flash(f"L'équipe « {nom} » existe déjà dans le classement.", "error")
        return redirect(url_for("classement"))
    supabase.table("classement").insert({
        "club_id": club_id, "nom_equipe": nom, "saison": saison,
        "matchs_joues": 0, "victoires": 0, "nuls": 0, "defaites": 0,
        "points_marques": 0, "points_encaisses": 0, "points_classement": 0,
    }).execute()
    flash(f"Équipe « {nom} » ajoutée.", "success")
    return redirect(url_for("classement"))


@app.route("/classement/renommer/<equipe_id>", methods=["POST"])
@coach_or_president
def renommer_equipe(equipe_id):
    club_id = session.get("club_id")
    nom     = request.form.get("nom_equipe", "").strip()
    if not nom:
        flash("Nom invalide.", "error")
        return redirect(url_for("classement"))
    supabase.table("classement").update({"nom_equipe": nom})\
            .eq("id", equipe_id).eq("club_id", club_id).execute()
    flash("Équipe renommée.", "success")
    return redirect(url_for("classement"))


@app.route("/classement/supprimer/<equipe_id>", methods=["POST"])
@coach_or_president
def supprimer_equipe(equipe_id):
    club_id = session.get("club_id")
    # Supprimer les résultats liés avant l'équipe
    supabase.table("resultats_classement").delete()\
            .eq("club_id", club_id)\
            .or_(f"equipe_dom_id.eq.{equipe_id},equipe_ext_id.eq.{equipe_id}")\
            .execute()
    supabase.table("classement").delete().eq("id", equipe_id).eq("club_id", club_id).execute()
    nom_club = session.get("nom_club", "")
    saison   = str(datetime.now().year)
    sport    = _get_sport(club_id)
    recalculate_classement(club_id, nom_club, saison, sport)
    flash("Équipe et ses résultats supprimés.", "success")
    return redirect(url_for("classement"))


@app.route("/classement/resultat/ajouter", methods=["POST"])
@coach_or_president
def ajouter_resultat():
    club_id   = session.get("club_id")
    saison    = request.form.get("saison", str(datetime.now().year))
    dom_id    = request.form.get("equipe_dom_id", "").strip()
    ext_id    = request.form.get("equipe_ext_id", "").strip()
    score_dom = int(request.form.get("score_dom", 0) or 0)
    score_ext = int(request.form.get("score_ext", 0) or 0)
    bonus_dom = int(request.form.get("bonus_dom", 0) or 0)
    bonus_ext = int(request.form.get("bonus_ext", 0) or 0)

    if not dom_id or not ext_id or dom_id == ext_id:
        flash("Sélectionne deux équipes différentes.", "error")
        return redirect(url_for("classement"))

    try:
        supabase.table("resultats_classement").insert({
            "club_id": club_id, "saison": saison,
            "equipe_dom_id": dom_id, "equipe_ext_id": ext_id,
            "score_dom": score_dom, "score_ext": score_ext,
            "bonus_dom": bonus_dom, "bonus_ext": bonus_ext,
            "source": "manuel",
        }).execute()
        nom_club = session.get("nom_club", "")
        sport    = _get_sport(club_id)
        recalculate_classement(club_id, nom_club, saison, sport)
        sync_notre_equipe(club_id, nom_club, saison, sport)
        flash("Résultat enregistré — classement mis à jour.", "success")
    except Exception as e:
        err = str(e)
        if "resultats_classement" in err or "does not exist" in err or "relation" in err:
            flash("Table manquante : exécute d'abord le SQL fourni dans Supabase "
                  "(CREATE TABLE resultats_classement…).", "error")
        else:
            flash(f"Erreur lors de l'enregistrement : {err}", "error")
    return redirect(url_for("classement"))


@app.route("/classement/resultat/supprimer/<resultat_id>", methods=["POST"])
@coach_or_president
def supprimer_resultat(resultat_id):
    club_id = session.get("club_id")
    res = supabase.table("resultats_classement").select("saison")\
                  .eq("id", resultat_id).eq("club_id", club_id).execute()
    saison = res.data[0]["saison"] if res.data else str(datetime.now().year)
    # Empêcher la suppression des résultats liés à /matchs (source='matchs')
    r2 = supabase.table("resultats_classement").select("source")\
                 .eq("id", resultat_id).eq("club_id", club_id).execute()
    if r2.data and r2.data[0].get("source") == "matchs":
        flash("Ce résultat est lié à un match — supprime-le depuis la page Matchs.", "error")
        return redirect(url_for("classement"))
    supabase.table("resultats_classement").delete()\
            .eq("id", resultat_id).eq("club_id", club_id).execute()
    nom_club = session.get("nom_club", "")
    sport    = _get_sport(club_id)
    recalculate_classement(club_id, nom_club, saison, sport)
    sync_notre_equipe(club_id, nom_club, saison, sport)
    flash("Résultat supprimé — classement recalculé.", "success")
    return redirect(url_for("classement"))


@app.route("/classement/reinitialiser", methods=["POST"])
@coach_or_president
def reinitialiser_classement():
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    saison   = request.form.get("saison", str(datetime.now().year))
    sport    = _get_sport(club_id)

    # 1. Supprimer tous les résultats manuels (source='manuel') de la saison
    try:
        supabase.table("resultats_classement").delete()\
                .eq("club_id", club_id).eq("saison", saison)\
                .eq("source", "manuel").execute()
    except Exception:
        pass

    # 2. Remettre à zéro toutes les équipes sauf la nôtre
    zero = {"matchs_joues": 0, "victoires": 0, "nuls": 0, "defaites": 0,
            "points_marques": 0, "points_encaisses": 0, "points_classement": 0}
    notre_id = get_or_create_equipe(club_id, nom_club, saison)
    eq_res   = supabase.table("classement").select("id")\
                       .eq("club_id", club_id).execute().data or []
    for eq in eq_res:
        if eq["id"] != notre_id:
            supabase.table("classement").update(dict(zero)).eq("id", eq["id"]).execute()

    # 3. Recalculer notre équipe depuis les matchs
    sync_notre_equipe(club_id, nom_club, saison, sport)

    flash("Classement réinitialisé. Les résultats manuels ont été supprimés.", "success")
    return redirect(url_for("classement"))


@app.route("/classement/recalculer", methods=["POST"])
@coach_or_president
def recalculer_classement():
    """Force la resynchronisation complète du classement depuis la table matchs.
    Utile après une correction de données ou lors d'une première utilisation."""
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    saison   = str(datetime.now().year)
    sport    = _get_sport(club_id)
    sync_notre_equipe(club_id, nom_club, saison, sport)
    recalculate_classement(club_id, nom_club, saison, sport)
    flash("Classement recalculé depuis tous les matchs enregistrés.", "success")
    return redirect(url_for("classement"))


# ══════════════════════════════════════════════════════════════════════════════
#  Analyse adversaire
# ══════════════════════════════════════════════════════════════════════════════

def _get_adversaires_list(club_id, nom_club):
    """Retourne la liste des équipes adverses depuis le classement."""
    try:
        res = supabase.table("classement").select("nom_equipe").eq("club_id", club_id).execute()
        return sorted({
            e["nom_equipe"] for e in (res.data or [])
            if (e.get("nom_equipe") or "").strip().lower() != nom_club.lower()
        })
    except Exception:
        return []


def _collect_analyse_data(club_id, saison):
    """Collecte les champs d'analyse depuis JSON (autosave) ou formulaire (POST)."""
    if request.is_json:
        body = request.get_json(silent=True) or {}
        nom_adversaire  = (body.get("nom_adversaire") or "").strip()
        saison_val      = body.get("saison") or saison
        style_jeu       = body.get("style_jeu") or None
        formation       = body.get("formation_adverse") or None
        niveau          = body.get("niveau_estime") or None
        notes           = body.get("notes_generales") or None
        points_forts    = body.get("points_forts") or []
        points_faibles  = body.get("points_faibles") or []
        plan_match      = body.get("plan_match") or {}
        bilan           = body.get("bilan_post_match") or {}
        match_id        = body.get("match_id") or None
    else:
        nom_adversaire  = request.form.get("nom_adversaire", "").strip()
        saison_val      = request.form.get("saison", saison)
        style_jeu       = request.form.get("style_jeu") or None
        formation       = request.form.get("formation_adverse") or None
        niveau          = request.form.get("niveau_estime") or None
        notes           = request.form.get("notes_generales") or None
        def _lj(field, default):
            raw = request.form.get(field, "")
            try:    return json.loads(raw) if raw else default
            except: return default
        points_forts   = _lj("points_forts", [])
        points_faibles = _lj("points_faibles", [])
        plan_match     = _lj("plan_match", {})
        bilan          = _lj("bilan_post_match", {})
        match_id       = request.form.get("match_id") or None
    return {
        "club_id": club_id, "nom_adversaire": nom_adversaire,
        "saison": saison_val, "style_jeu": style_jeu,
        "formation_adverse": formation, "niveau_estime": niveau,
        "notes_generales": notes, "points_forts": points_forts,
        "points_faibles": points_faibles, "plan_match": plan_match,
        "bilan_post_match": bilan, "match_id": match_id,
    }


@app.route("/analyse-adversaire")
@login_required
def analyse_adversaire():
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    saison   = str(datetime.now().year)
    try:
        res = supabase.table("analyses_adversaires")\
                      .select("id,nom_adversaire,saison,style_jeu,niveau_estime,updated_at")\
                      .eq("club_id", club_id)\
                      .order("updated_at", desc=True).execute()
        analyses = res.data or []
    except Exception:
        analyses = []
    adversaires = _get_adversaires_list(club_id, nom_club)
    return render_template("analyse_adversaire.html",
                           analyses=analyses, adversaires=adversaires,
                           saison=saison, nom_club=nom_club)


@app.route("/analyse-adversaire/nouveau", methods=["GET", "POST"])
@coach_or_president
def nouvelle_analyse():
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    saison   = str(datetime.now().year)
    if request.method == "POST":
        data = _collect_analyse_data(club_id, saison)
        if not data["nom_adversaire"]:
            flash("Le nom de l'adversaire est obligatoire.", "error")
            return redirect(url_for("nouvelle_analyse"))
        try:
            res = supabase.table("analyses_adversaires").insert(data).execute()
            if res.data:
                flash("Fiche créée — continuez à la remplir.", "success")
                return redirect(url_for("edit_analyse", analyse_id=res.data[0]["id"]))
        except Exception as e:
            flash(f"Erreur lors de la création : {e}", "error")
        return redirect(url_for("analyse_adversaire"))
    adversaires = _get_adversaires_list(club_id, nom_club)
    sport = _get_sport(club_id)
    show_formation = sport in ("Football", "Football américain")
    return render_template("analyse_adversaire_form.html",
                           analyse=None, adversaires=adversaires,
                           saison=saison, nom_club=nom_club,
                           sport=sport, show_formation=show_formation)


@app.route("/analyse-adversaire/<analyse_id>", methods=["GET"])
@coach_or_president
def edit_analyse(analyse_id):
    club_id  = session.get("club_id")
    nom_club = session.get("nom_club", "")
    saison   = str(datetime.now().year)
    try:
        res = supabase.table("analyses_adversaires").select("*")\
                      .eq("id", analyse_id).eq("club_id", club_id).execute()
        if not res.data:
            flash("Fiche introuvable.", "error")
            return redirect(url_for("analyse_adversaire"))
        analyse = res.data[0]
    except Exception as e:
        flash(f"Erreur : {e}", "error")
        return redirect(url_for("analyse_adversaire"))
    adversaires = _get_adversaires_list(club_id, nom_club)
    sport = _get_sport(club_id)
    show_formation = sport in ("Football", "Football américain")
    return render_template("analyse_adversaire_form.html",
                           analyse=analyse, adversaires=adversaires,
                           saison=saison, nom_club=nom_club,
                           sport=sport, show_formation=show_formation)


@app.route("/analyse-adversaire/<analyse_id>/sauvegarder", methods=["POST"])
@coach_or_president
def sauvegarder_analyse(analyse_id):
    from flask import jsonify
    club_id  = session.get("club_id")
    saison   = str(datetime.now().year)
    is_auto  = request.headers.get("X-Autosave") == "true"
    data     = _collect_analyse_data(club_id, saison)
    data["updated_at"] = datetime.utcnow().isoformat()
    try:
        supabase.table("analyses_adversaires").update(data)\
                .eq("id", analyse_id).eq("club_id", club_id).execute()
        if is_auto:
            return jsonify({"ok": True, "updated_at": data["updated_at"]}), 200
        flash("Analyse sauvegardée.", "success")
    except Exception as e:
        if is_auto:
            return jsonify({"ok": False, "error": str(e)}), 500
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("edit_analyse", analyse_id=analyse_id))


@app.route("/analyse-adversaire/<analyse_id>/supprimer", methods=["POST"])
@coach_or_president
def supprimer_analyse(analyse_id):
    club_id = session.get("club_id")
    try:
        supabase.table("analyses_adversaires").delete()\
                .eq("id", analyse_id).eq("club_id", club_id).execute()
        flash("Fiche supprimée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("analyse_adversaire"))


# ══════════════════════════════════════════════════════════════════════════════
#  Planning — Séances d'entraînement
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/planning")
@login_required
def planning():
    club_id = session.get("club_id")
    today   = datetime.now().strftime("%Y-%m-%d")
    saison  = str(datetime.now().year)

    # Séances (toutes, triées par date)
    try:
        res = supabase.table("seances").select("*")\
                      .eq("club_id", club_id)\
                      .order("date_seance").order("heure_debut").execute()
        seances = res.data or []
    except Exception:
        seances = []

    # Matchs à venir non encore joués
    try:
        mr = supabase.table("matchs").select("*")\
                     .eq("club_id", club_id)\
                     .gte("date_match", today)\
                     .is_("score_nous", "null")\
                     .order("date_match").execute()
        matchs_futurs = mr.data or []
    except Exception:
        matchs_futurs = []

    # Joueurs pour la liste de présence
    try:
        jr = supabase.table("joueurs").select("id,prenom,nom")\
                     .eq("club_id", club_id).order("nom").execute()
        joueurs = jr.data or []
    except Exception:
        joueurs = []

    # Fusion événements triés par date
    events = []
    for s in seances:
        events.append({**s, "_type": "seance", "date": s.get("date_seance", "")})
    for m in matchs_futurs:
        events.append({
            "_type":     "match",
            "id":        m.get("id"),
            "date":      m.get("date_match", ""),
            "adversaire": m.get("adversaire", ""),
            "domicile":  m.get("domicile", True),
            "notes":     m.get("notes"),
        })
    events.sort(key=lambda e: e.get("date") or "")

    # Premier événement futur (prochain match ou séance)
    prochain_event = next((e for e in events if (e.get("date") or "") >= today), None)

    return render_template("planning.html",
                           events=events, seances=seances,
                           matchs_futurs=matchs_futurs,
                           joueurs=joueurs, today=today,
                           prochain_event=prochain_event,
                           saison=saison)


@app.route("/planning/ajouter", methods=["POST"])
@coach_or_president
def ajouter_seance():
    club_id = session.get("club_id")
    date_s  = request.form.get("date_seance", "").strip()
    heure_d = request.form.get("heure_debut", "").strip() or None
    heure_f = request.form.get("heure_fin",   "").strip() or None
    lieu    = request.form.get("lieu",    "").strip() or None
    theme   = request.form.get("theme",   "").strip() or None
    notes   = request.form.get("notes",   "").strip() or None
    presents_raw = request.form.get("presents", "")
    try:
        presents = json.loads(presents_raw) if presents_raw else []
    except Exception:
        presents = []
    if not date_s:
        flash("La date est obligatoire.", "error")
        return redirect(url_for("planning"))
    try:
        res_s = supabase.table("seances").insert({
            "club_id": club_id, "date_seance": date_s,
            "heure_debut": heure_d, "heure_fin": heure_f,
            "lieu": lieu, "theme": theme, "notes": notes,
            "presents": presents,
        }).execute()
        if res_s.data:
            seance_id  = res_s.data[0]["id"]
            titre_j    = f"Entraînement{' — ' + theme if theme else ''}"
            contenu_j  = (f"Lieu : {lieu}. " if lieu else "") + (notes or "")
            _auto_journal_entry(
                club_id=club_id, equipe_id=session.get("equipe_id"),
                date_entree=date_s, titre=titre_j,
                contenu=contenu_j.strip() or None,
                categorie="Entraînement", source="seance", source_id=seance_id,
            )
        flash("Séance ajoutée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("planning"))


@app.route("/planning/modifier/<seance_id>", methods=["POST"])
@coach_or_president
def modifier_seance(seance_id):
    club_id = session.get("club_id")
    date_s  = request.form.get("date_seance", "").strip()
    heure_d = request.form.get("heure_debut", "").strip() or None
    heure_f = request.form.get("heure_fin",   "").strip() or None
    lieu    = request.form.get("lieu",    "").strip() or None
    theme   = request.form.get("theme",   "").strip() or None
    notes   = request.form.get("notes",   "").strip() or None
    presents_raw = request.form.get("presents", "")
    try:
        presents = json.loads(presents_raw) if presents_raw else []
    except Exception:
        presents = []
    if not date_s:
        flash("La date est obligatoire.", "error")
        return redirect(url_for("planning"))
    try:
        supabase.table("seances").update({
            "date_seance": date_s, "heure_debut": heure_d, "heure_fin": heure_f,
            "lieu": lieu, "theme": theme, "notes": notes, "presents": presents,
        }).eq("id", seance_id).eq("club_id", club_id).execute()
        flash("Séance modifiée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("planning"))


@app.route("/planning/supprimer/<seance_id>", methods=["POST"])
@coach_or_president
def supprimer_seance(seance_id):
    club_id = session.get("club_id")
    try:
        supabase.table("seances").delete()\
                .eq("id", seance_id).eq("club_id", club_id).execute()
        flash("Séance supprimée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("planning"))


# ══════════════════════════════════════════════════════════════════════════════
#  Séances — Préparation détaillée
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/seances")
@coach_or_president
def seances_prep():
    club_id = session.get("club_id")
    try:
        res = supabase.table("seances").select("id,date_seance,heure_debut,duree_minutes,theme,statut,analyse_adversaire_id")\
                      .eq("club_id", club_id)\
                      .order("date_seance", desc=True).execute()
        seances = res.data or []
    except Exception:
        seances = []
    # Analyses adversaires pour le menu déroulant
    try:
        ar = supabase.table("analyses_adversaires")\
                     .select("id,nom_adversaire,saison")\
                     .eq("club_id", club_id)\
                     .order("updated_at", desc=True).execute()
        analyses = ar.data or []
    except Exception:
        analyses = []
    analyses_map = {a["id"]: a for a in analyses}
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("seances_prep.html",
                           seances=seances, analyses=analyses,
                           analyses_map=analyses_map, today=today)


@app.route("/seances/nouveau", methods=["GET"])
@coach_or_president
def nouvelle_seance_prep():
    club_id = session.get("club_id")
    try:
        ar = supabase.table("analyses_adversaires")\
                     .select("id,nom_adversaire,saison")\
                     .eq("club_id", club_id)\
                     .order("updated_at", desc=True).execute()
        analyses = ar.data or []
    except Exception:
        analyses = []
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("seance_form.html",
                           seance=None, analyses=analyses, today=today,
                           analyse_liee=None)


@app.route("/seances/creer", methods=["POST"])
@coach_or_president
def creer_seance_prep():
    club_id = session.get("club_id")
    date_s  = request.form.get("date_seance", "").strip()
    heure   = request.form.get("heure_debut", "").strip() or None
    duree   = request.form.get("duree_minutes", "").strip()
    theme = request.form.get("objectif", "").strip() or None
    notes   = request.form.get("notes", "").strip() or None
    statut  = request.form.get("statut", "Planifiée").strip()
    analyse_id = request.form.get("analyse_adversaire_id", "").strip() or None
    exercices_raw = request.form.get("exercices", "[]")
    try:
        exercices = json.loads(exercices_raw)
    except Exception:
        exercices = []
    if not date_s:
        flash("La date est obligatoire.", "error")
        return redirect(url_for("nouvelle_seance_prep"))
    try:
        res = supabase.table("seances").insert({
            "club_id": club_id,
            "date_seance": date_s,
            "heure_debut": heure,
            "duree_minutes": int(duree) if duree else None,
            "theme": theme,
            "notes": notes,
            "statut": statut,
            "analyse_adversaire_id": analyse_id,
            "exercices": exercices,
        }).execute()
        flash("Séance créée.", "success")
        if res.data:
            return redirect(url_for("edit_seance_prep", seance_id=res.data[0]["id"]))
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("seances_prep"))


@app.route("/seances/<seance_id>", methods=["GET"])
@coach_or_president
def edit_seance_prep(seance_id):
    club_id = session.get("club_id")
    try:
        res = supabase.table("seances").select("*")\
                      .eq("id", seance_id).eq("club_id", club_id).execute()
        if not res.data:
            flash("Séance introuvable.", "error")
            return redirect(url_for("seances_prep"))
        seance = res.data[0]
    except Exception as e:
        flash(f"Erreur : {e}", "error")
        return redirect(url_for("seances_prep"))
    # Analyses
    try:
        ar = supabase.table("analyses_adversaires")\
                     .select("id,nom_adversaire,saison,points_faibles")\
                     .eq("club_id", club_id)\
                     .order("updated_at", desc=True).execute()
        analyses = ar.data or []
    except Exception:
        analyses = []
    analyse_liee = None
    if seance.get("analyse_adversaire_id"):
        for a in analyses:
            if a["id"] == seance["analyse_adversaire_id"]:
                analyse_liee = a
                break
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("seance_form.html",
                           seance=seance, analyses=analyses, today=today,
                           analyse_liee=analyse_liee)


@app.route("/seances/<seance_id>/modifier", methods=["POST"])
@coach_or_president
def modifier_seance_prep(seance_id):
    club_id = session.get("club_id")
    date_s  = request.form.get("date_seance", "").strip()
    heure   = request.form.get("heure_debut", "").strip() or None
    duree   = request.form.get("duree_minutes", "").strip()
    theme = request.form.get("objectif", "").strip() or None
    notes   = request.form.get("notes", "").strip() or None
    statut  = request.form.get("statut", "Planifiée").strip()
    analyse_id = request.form.get("analyse_adversaire_id", "").strip() or None
    exercices_raw = request.form.get("exercices", "[]")
    try:
        exercices = json.loads(exercices_raw)
    except Exception:
        exercices = []
    if not date_s:
        flash("La date est obligatoire.", "error")
        return redirect(url_for("edit_seance_prep", seance_id=seance_id))
    try:
        supabase.table("seances").update({
            "date_seance": date_s,
            "heure_debut": heure,
            "duree_minutes": int(duree) if duree else None,
            "theme": theme,
            "notes": notes,
            "statut": statut,
            "analyse_adversaire_id": analyse_id,
            "exercices": exercices,
        }).eq("id", seance_id).eq("club_id", club_id).execute()
        flash("Séance enregistrée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("edit_seance_prep", seance_id=seance_id))


@app.route("/seances/<seance_id>/supprimer", methods=["POST"])
@coach_or_president
def supprimer_seance_prep(seance_id):
    club_id = session.get("club_id")
    try:
        supabase.table("seances").delete()\
                .eq("id", seance_id).eq("club_id", club_id).execute()
        flash("Séance supprimée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("seances_prep"))


# ══════════════════════════════════════════════════════════════════════════════
#  Blessures / Indisponibilités
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_indispos_actives(club_id):
    """Retourne dict {joueur_id(str): indispo_row} pour les indispos actives."""
    try:
        from datetime import date as _date
        rows = supabase.table("indisponibilites").select("*")\
                       .eq("club_id", club_id).eq("actif", True).execute().data or []
        today = _date.today()
        result = {}
        for r in rows:
            debut = r.get("date_debut")
            r["nb_jours"] = (today - _date.fromisoformat(debut)).days if debut else 0
            result[str(r["joueur_id"])] = r
        return result
    except Exception:
        return {}


@app.route("/blessures")
@coach_or_president
def blessures():
    from datetime import date as _date
    club_id  = session.get("club_id")
    saison   = str(datetime.now().year)

    # Effectif pour le sélecteur
    try:
        jr = supabase.table("joueurs").select("id,prenom,nom,poste,photo_url")\
                     .eq("club_id", club_id).order("nom").execute()
        joueurs = jr.data or []
    except Exception:
        joueurs = []

    # Indispos actives (avec nb_jours)
    try:
        actives_raw = supabase.table("indisponibilites").select("*")\
                              .eq("club_id", club_id).eq("actif", True)\
                              .order("date_debut", desc=True).execute().data or []
        today = _date.today()
        for r in actives_raw:
            debut = r.get("date_debut")
            r["nb_jours"] = (today - _date.fromisoformat(debut)).days if debut else 0
    except Exception:
        actives_raw = []

    # Historique saison (actif = False)
    try:
        hist_raw = supabase.table("indisponibilites").select("*")\
                           .eq("club_id", club_id).eq("actif", False)\
                           .order("date_debut", desc=True).limit(50).execute().data or []
    except Exception:
        hist_raw = []

    # Index joueurs par id pour affichage
    joueurs_by_id = {str(j["id"]): j for j in joueurs}

    return render_template("blessures.html",
                           joueurs=joueurs, joueurs_by_id=joueurs_by_id,
                           actives=actives_raw, historique=hist_raw,
                           indispo_types=INDISPO_TYPES,
                           indispo_gravite=INDISPO_GRAVITE)


@app.route("/blessures/declarer", methods=["POST"])
@coach_or_president
def blessures_declarer():
    from datetime import date as _date
    club_id    = session.get("club_id")
    joueur_id  = request.form.get("joueur_id", "").strip()
    type_i     = request.form.get("type_indispo", "Blessure").strip()
    description= request.form.get("description", "").strip()
    gravite    = request.form.get("gravite", "").strip() or None
    date_debut = request.form.get("date_debut", "").strip() or str(_date.today())
    date_retour= request.form.get("date_retour_estimee", "").strip() or None

    if not joueur_id:
        flash("Sélectionnez un joueur.", "error")
        return redirect(url_for("blessures"))

    # Récupère infos joueur
    try:
        jr = supabase.table("joueurs").select("prenom,nom")\
                     .eq("id", joueur_id).eq("club_id", club_id).execute()
        joueur_info = jr.data[0] if jr.data else {}
    except Exception:
        joueur_info = {}

    equipe_id = session.get("equipe_id")
    saison = date_debut[:4] if date_debut else str(datetime.now().year)

    row = {
        "club_id":             club_id,
        "joueur_id":           joueur_id,
        "type":                type_i,
        "description":         description,
        "gravite":             gravite,
        "date_debut":          date_debut,
        "date_retour_estimee": date_retour,
        "actif":               True,
        "saison":              saison,
    }
    if equipe_id:
        row["equipe_id"] = str(equipe_id)

    try:
        supabase.table("indisponibilites").insert(row).execute()

        # Auto-entrée journal
        nom_j = f"{joueur_info.get('prenom','')} {joueur_info.get('nom','')}".strip()
        contenu_j = f"Joueur : {nom_j}\nType : {type_i}"
        if gravite:
            contenu_j += f" ({gravite})"
        if description:
            contenu_j += f"\nDescription : {description}"
        if date_retour:
            contenu_j += f"\nRetour estimé : {date_retour}"
        _auto_journal_entry(
            club_id=club_id, equipe_id=equipe_id,
            date_entree=date_debut,
            titre=f"Indisponibilité — {nom_j}",
            contenu=contenu_j,
            categorie="Blessure", source="manuel",
        )
        flash(f"Indisponibilité déclarée pour {nom_j}.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")

    return redirect(url_for("blessures"))


@app.route("/blessures/clore/<indispo_id>", methods=["POST"])
@coach_or_president
def blessures_clore(indispo_id):
    from datetime import date as _date
    club_id = session.get("club_id")
    try:
        supabase.table("indisponibilites").update({
            "actif": False,
            "date_retour_effective": str(_date.today()),
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", indispo_id).eq("club_id", club_id).execute()
        flash("Joueur marqué comme disponible.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("blessures"))


@app.route("/blessures/supprimer/<indispo_id>", methods=["POST"])
@coach_or_president
def blessures_supprimer(indispo_id):
    club_id = session.get("club_id")
    try:
        supabase.table("indisponibilites").delete()\
                .eq("id", indispo_id).eq("club_id", club_id).execute()
        flash("Indisponibilité supprimée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("blessures"))


# ══════════════════════════════════════════════════════════════════════════════
#  Journal de bord
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/journal")
@coach_or_president
def journal():
    club_id   = session.get("club_id")
    role      = session.get("role", "president")
    saison    = request.args.get("saison", str(datetime.now().year))
    cat_f     = request.args.get("categorie", "")
    q_str     = request.args.get("q", "").strip()
    equipe_id = session.get("equipe_id") if role != "president" \
                else request.args.get("equipe", "")

    equipes = []
    if role == "president":
        try:
            r = supabase.table("equipes_club").select("id,nom")\
                        .eq("club_id", club_id).order("nom").execute()
            equipes = r.data or []
        except Exception:
            pass

    try:
        q = supabase.table("journal").select("*")\
                    .eq("club_id", club_id).eq("saison", saison)\
                    .order("date_entree", desc=True)\
                    .order("created_at", desc=True)
        if equipe_id:
            q = q.eq("equipe_id", str(equipe_id))
        if cat_f:
            q = q.eq("categorie", cat_f)
        entries = q.execute().data or []
    except Exception:
        entries = []

    if q_str:
        sl = q_str.lower()
        entries = [e for e in entries
                   if sl in (e.get("titre") or "").lower()
                   or sl in (e.get("contenu") or "").lower()]

    try:
        all_s = supabase.table("journal").select("saison")\
                        .eq("club_id", club_id).execute().data or []
        saisons = sorted({r["saison"] for r in all_s if r.get("saison")}, reverse=True)
        if not saisons:
            saisons = [str(datetime.now().year)]
    except Exception:
        saisons = [str(datetime.now().year)]

    return render_template("journal.html",
                           entries=entries, equipes=equipes,
                           selected_equipe=str(equipe_id) if equipe_id else "",
                           saison=saison, saisons=saisons,
                           cat_filter=cat_f, q=q_str,
                           categories=JOURNAL_CATEGORIES,
                           humeurs=JOURNAL_HUMEURS,
                           cat_colors=JOURNAL_CAT_COLORS,
                           mood_emoji=JOURNAL_MOOD_EMOJI,
                           role=role)


@app.route("/journal/ajouter", methods=["POST"])
@coach_or_president
def journal_ajouter():
    club_id   = session.get("club_id")
    role      = session.get("role", "president")
    equipe_id = session.get("equipe_id") if role != "president" \
                else (request.form.get("equipe_id") or None)
    date_e    = request.form.get("date_entree", "").strip()
    titre     = request.form.get("titre", "").strip()
    contenu   = request.form.get("contenu", "").strip()
    categorie = request.form.get("categorie", "Autre")
    humeur    = request.form.get("humeur", "").strip() or None
    if not date_e or not titre:
        flash("La date et le titre sont obligatoires.", "error")
        return redirect(url_for("journal"))
    saison = date_e[:4]
    row = {
        "club_id": club_id, "date_entree": date_e, "titre": titre,
        "contenu": contenu, "categorie": categorie, "humeur": humeur,
        "source": "manuel", "saison": saison,
    }
    if equipe_id:
        row["equipe_id"] = str(equipe_id)
    try:
        supabase.table("journal").insert(row).execute()
        flash("Entrée ajoutée au journal.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("journal", saison=saison))


@app.route("/journal/modifier/<entry_id>", methods=["POST"])
@coach_or_president
def journal_modifier(entry_id):
    club_id   = session.get("club_id")
    date_e    = request.form.get("date_entree", "").strip()
    titre     = request.form.get("titre", "").strip()
    contenu   = request.form.get("contenu", "").strip()
    categorie = request.form.get("categorie", "Autre")
    humeur    = request.form.get("humeur", "").strip() or None
    if not date_e or not titre:
        flash("La date et le titre sont obligatoires.", "error")
        return redirect(url_for("journal"))
    try:
        supabase.table("journal").update({
            "date_entree": date_e, "titre": titre, "contenu": contenu,
            "categorie": categorie, "humeur": humeur,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", entry_id).eq("club_id", club_id).execute()
        flash("Entrée modifiée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("journal", saison=date_e[:4] if date_e else ""))


@app.route("/journal/supprimer/<entry_id>", methods=["POST"])
@coach_or_president
def journal_supprimer(entry_id):
    club_id = session.get("club_id")
    try:
        supabase.table("journal").delete()\
                .eq("id", entry_id).eq("club_id", club_id).execute()
        flash("Entrée supprimée.", "success")
    except Exception as e:
        flash(f"Erreur : {e}", "error")
    return redirect(url_for("journal"))


@app.route("/journal/export")
@coach_or_president
def journal_export():
    club_id   = session.get("club_id")
    role      = session.get("role", "president")
    saison    = request.args.get("saison", str(datetime.now().year))
    equipe_id = session.get("equipe_id") if role != "president" \
                else request.args.get("equipe", "")
    try:
        q = supabase.table("journal").select("*")\
                    .eq("club_id", club_id).eq("saison", saison)\
                    .order("date_entree", desc=False)
        if equipe_id:
            q = q.eq("equipe_id", str(equipe_id))
        entries = q.execute().data or []
    except Exception:
        entries = []
    equipe_nom = ""
    if equipe_id:
        try:
            r = supabase.table("equipes_club").select("nom")\
                        .eq("id", str(equipe_id)).execute()
            equipe_nom = r.data[0]["nom"] if r.data else ""
        except Exception:
            pass
    now_str = datetime.now().strftime("%d/%m/%Y")
    return render_template("journal_export.html",
                           entries=entries,
                           nom_club=session.get("nom_club", ""),
                           equipe_nom=equipe_nom, saison=saison,
                           now=now_str,
                           cat_colors=JOURNAL_CAT_COLORS,
                           mood_emoji=JOURNAL_MOOD_EMOJI)


# ══════════════════════════════════════════════════════════════════════════════
#  Messagerie
# ══════════════════════════════════════════════════════════════════════════════

# ── Messagerie helpers ────────────────────────────────────────────────────────

CHANNEL_INFO = {
    "general":      ("📢", "Général",       "Annonces du coach"),
    "convocations": ("📅", "Convocations",  "Listes de convocation"),
    "discussion":   ("💬", "Discussion",    "Échanges libres de l'équipe"),
}
CHANNEL_ORDER = {"general": 0, "convocations": 1, "discussion": 2}

def _user_key():
    if session.get("role") == "president":
        return f"pres_{session.get('club_id')}"
    return f"mbr_{session.get('membre_id')}"

def _user_nom():
    if session.get("role") == "president":
        return session.get("nom_club", "Président")
    return session.get("nom_membre", "Membre")

def _nom_from_key(key, membres, nom_club):
    if not key:
        return "?"
    if key.startswith("pres_"):
        return f"🏟️ {nom_club}"
    mid = key.replace("mbr_", "")
    for m in membres:
        if str(m["id"]) == mid:
            return f"{m.get('prenom','')} {m.get('nom','')}".strip()
    return "Membre"

def _ensure_equipe_channels(club_id, equipe_id):
    """Crée les 3 canaux par défaut d'une équipe si absents."""
    for t in ("general", "convocations", "discussion"):
        try:
            r = supabase.table("msg_conversations").select("id")\
                        .eq("club_id", club_id).eq("equipe_id", str(equipe_id)).eq("type", t).execute()
            if not r.data:
                supabase.table("msg_conversations").insert({
                    "club_id": club_id, "equipe_id": str(equipe_id), "type": t,
                }).execute()
        except Exception:
            pass

def _get_msg_sidebar(club_id, role, user_key, equipe_id=None, selected_conv_id=None):
    """Retourne toutes les données nécessaires à la sidebar messagerie."""
    # Équipes accessibles
    try:
        if role == "president":
            eq_res = supabase.table("equipes_club").select("*").eq("club_id", club_id).execute()
        elif equipe_id:
            eq_res = supabase.table("equipes_club").select("*").eq("id", equipe_id).execute()
        else:
            eq_res = None
        equipes = eq_res.data if eq_res else []
    except Exception:
        equipes = []

    equipe_ids = [str(e["id"]) for e in equipes]

    # Canaux d'équipe
    team_convs = []
    if equipe_ids:
        try:
            for eid in equipe_ids:
                r = supabase.table("msg_conversations").select("*")\
                            .eq("club_id", club_id).eq("equipe_id", eid)\
                            .in_("type", list(CHANNEL_INFO.keys())).execute()
                team_convs.extend(r.data or [])
        except Exception:
            pass

    for c in team_convs:
        icon, name, _ = CHANNEL_INFO.get(c.get("type"), ("💬", c.get("type"), ""))
        c["display_icon"] = icon
        c["display_name"] = name

    # Grouper par équipe, triés
    convs_by_equipe = {}
    for c in team_convs:
        eid = str(c.get("equipe_id", ""))
        convs_by_equipe.setdefault(eid, []).append(c)
    for eid in convs_by_equipe:
        convs_by_equipe[eid].sort(key=lambda c: CHANNEL_ORDER.get(c.get("type"), 9))

    # DMs
    try:
        dm1 = supabase.table("msg_conversations").select("*")\
                      .eq("club_id", club_id).eq("type", "perso").eq("user_key1", user_key).execute()
        dm2 = supabase.table("msg_conversations").select("*")\
                      .eq("club_id", club_id).eq("type", "perso").eq("user_key2", user_key).execute()
        dm_convs = (dm1.data or []) + (dm2.data or [])
    except Exception:
        dm_convs = []

    # Membres pour noms DMs
    try:
        mbr_res = supabase.table("membres").select("id,prenom,nom,role")\
                          .eq("club_id", club_id).execute()
        membres = mbr_res.data or []
    except Exception:
        membres = []

    nom_club = session.get("nom_club", "")
    for c in dm_convs:
        other = c.get("user_key2") if c.get("user_key1") == user_key else c.get("user_key1")
        c["display_name"] = _nom_from_key(other, membres, nom_club)
        c["display_icon"] = "💬"

    # last_msgs + unread
    all_ids = [c["id"] for c in team_convs + dm_convs]
    last_msgs, unread_counts = {}, {}
    try:
        lu_map = {r["conv_id"]: r["lu_at"]
                  for r in (supabase.table("msg_lu").select("conv_id,lu_at")
                                    .eq("user_key", user_key).execute().data or [])}
    except Exception:
        lu_map = {}

    for cid in all_ids:
        try:
            lm = supabase.table("msg_messages").select("sender_nom,content,created_at")\
                         .eq("conv_id", cid).order("created_at", desc=True).limit(1).execute()
            if lm.data:
                last_msgs[cid] = lm.data[0]
        except Exception:
            pass
        if cid == selected_conv_id:
            unread_counts[cid] = 0
        else:
            lu_at = lu_map.get(cid)
            try:
                q = supabase.table("msg_messages").select("id")\
                            .eq("conv_id", cid).neq("user_key", user_key)
                if lu_at:
                    q = q.gt("created_at", lu_at)
                unread_counts[cid] = len(q.execute().data or [])
            except Exception:
                unread_counts[cid] = 0

    return equipes, convs_by_equipe, dm_convs, membres, last_msgs, unread_counts


def _resolve_equipe_id(club_id, role):
    """Détermine l'equipe_id courant pour la sidebar."""
    equipe_id = request.args.get("equipe") or session.get("equipe_id")
    if role == "president" and not equipe_id:
        try:
            r = supabase.table("equipes_club").select("id").eq("club_id", club_id).limit(1).execute()
            if r.data:
                equipe_id = r.data[0]["id"]
        except Exception:
            pass
    return equipe_id


@app.route("/messagerie")
@login_required
def messagerie():
    club_id  = session.get("club_id")
    role     = session.get("role", "president")
    user_key = _user_key()
    equipe_id = _resolve_equipe_id(club_id, role)
    if equipe_id:
        _ensure_equipe_channels(club_id, equipe_id)
    equipes, convs_by_equipe, dm_convs, membres, last_msgs, unread_counts = \
        _get_msg_sidebar(club_id, role, user_key, equipe_id=equipe_id)
    return render_template("messagerie.html",
                           equipes=equipes, convs_by_equipe=convs_by_equipe,
                           dm_convs=dm_convs, membres=membres,
                           last_msgs=last_msgs, unread_counts=unread_counts,
                           user_key=user_key, role=role,
                           selected_equipe_id=str(equipe_id) if equipe_id else None,
                           selected_conv=None, messages=[], conv_name="", conv_sub="")


@app.route("/messagerie/<conv_id>")
@login_required
def messagerie_conv(conv_id):
    club_id  = session.get("club_id")
    role     = session.get("role", "president")
    user_key = _user_key()

    try:
        cr = supabase.table("msg_conversations").select("*")\
                     .eq("id", conv_id).eq("club_id", club_id).execute()
        if not cr.data:
            flash("Conversation introuvable.", "error")
            return redirect(url_for("messagerie"))
        conv = cr.data[0]
    except Exception:
        return redirect(url_for("messagerie"))

    t         = conv.get("type")
    equipe_id = conv.get("equipe_id") or _resolve_equipe_id(club_id, role)

    # Contrôle d'accès
    if t != "perso":
        if role != "president":
            if not equipe_id or str(equipe_id) != str(conv.get("equipe_id", "")):
                return redirect(url_for("messagerie"))
    else:
        if user_key not in (conv.get("user_key1"), conv.get("user_key2")):
            return redirect(url_for("messagerie"))

    if equipe_id:
        _ensure_equipe_channels(club_id, equipe_id)

    try:
        messages = supabase.table("msg_messages").select("*")\
                           .eq("conv_id", conv_id).order("created_at", desc=False).execute().data or []
    except Exception:
        messages = []

    try:
        supabase.table("msg_lu").upsert(
            {"conv_id": conv_id, "user_key": user_key,
             "lu_at": datetime.utcnow().isoformat()},
            on_conflict="conv_id,user_key"
        ).execute()
    except Exception:
        pass

    equipes, convs_by_equipe, dm_convs, membres, last_msgs, unread_counts = \
        _get_msg_sidebar(club_id, role, user_key, equipe_id=equipe_id, selected_conv_id=conv_id)

    if t in CHANNEL_INFO:
        _, conv_name, conv_sub = CHANNEL_INFO[t]
    elif t == "perso":
        other = conv.get("user_key2") if conv.get("user_key1") == user_key else conv.get("user_key1")
        conv_name = _nom_from_key(other, membres, session.get("nom_club", ""))
        conv_sub  = "Message direct"
    else:
        conv_name, conv_sub = "Conversation", ""

    return render_template("messagerie.html",
                           equipes=equipes, convs_by_equipe=convs_by_equipe,
                           dm_convs=dm_convs, membres=membres,
                           last_msgs=last_msgs, unread_counts=unread_counts,
                           user_key=user_key, role=role,
                           selected_equipe_id=str(equipe_id) if equipe_id else None,
                           selected_conv=conv, messages=messages,
                           conv_name=conv_name, conv_sub=conv_sub)


@app.route("/messagerie/<conv_id>/envoyer", methods=["POST"])
@login_required
def messagerie_envoyer(conv_id):
    club_id  = session.get("club_id")
    role     = session.get("role", "president")
    user_key = _user_key()
    content  = request.form.get("content", "").strip()
    if not content:
        return redirect(url_for("messagerie_conv", conv_id=conv_id))
    try:
        cr = supabase.table("msg_conversations").select("type,equipe_id,user_key1,user_key2")\
                     .eq("id", conv_id).eq("club_id", club_id).execute()
        if not cr.data:
            return redirect(url_for("messagerie"))
        conv = cr.data[0]
    except Exception:
        return redirect(url_for("messagerie"))

    t = conv.get("type")
    if t != "perso":
        if role != "president":
            equipe_id = session.get("equipe_id")
            if not equipe_id or str(equipe_id) != str(conv.get("equipe_id", "")):
                return redirect(url_for("messagerie"))
    else:
        if user_key not in (conv.get("user_key1"), conv.get("user_key2")):
            return redirect(url_for("messagerie"))

    try:
        supabase.table("msg_messages").insert({
            "conv_id": conv_id, "club_id": club_id,
            "user_key": user_key, "sender_nom": _user_nom(),
            "sender_role": role, "content": content,
        }).execute()
        supabase.table("msg_lu").upsert(
            {"conv_id": conv_id, "user_key": user_key,
             "lu_at": datetime.utcnow().isoformat()},
            on_conflict="conv_id,user_key"
        ).execute()
    except Exception:
        pass
    return redirect(url_for("messagerie_conv", conv_id=conv_id))


@app.route("/messagerie/nouveau/<membre_id>")
@login_required
def messagerie_nouveau_dm(membre_id):
    club_id   = session.get("club_id")
    user_key  = _user_key()
    other_key = f"mbr_{membre_id}"
    if user_key == other_key:
        return redirect(url_for("messagerie"))
    try:
        for k1, k2 in [(user_key, other_key), (other_key, user_key)]:
            r = supabase.table("msg_conversations").select("id")\
                        .eq("club_id", club_id).eq("type", "perso")\
                        .eq("user_key1", k1).eq("user_key2", k2).execute()
            if r.data:
                return redirect(url_for("messagerie_conv", conv_id=r.data[0]["id"]))
        res = supabase.table("msg_conversations").insert({
            "club_id": club_id, "type": "perso",
            "user_key1": user_key, "user_key2": other_key,
        }).execute()
        if res.data:
            return redirect(url_for("messagerie_conv", conv_id=res.data[0]["id"]))
    except Exception:
        pass
    return redirect(url_for("messagerie"))


@app.route("/messagerie/dm-president")
@login_required
def messagerie_dm_president():
    club_id  = session.get("club_id")
    user_key = _user_key()
    pres_key = f"pres_{club_id}"
    if user_key == pres_key:
        return redirect(url_for("messagerie"))
    try:
        for k1, k2 in [(user_key, pres_key), (pres_key, user_key)]:
            r = supabase.table("msg_conversations").select("id")\
                        .eq("club_id", club_id).eq("type", "perso")\
                        .eq("user_key1", k1).eq("user_key2", k2).execute()
            if r.data:
                return redirect(url_for("messagerie_conv", conv_id=r.data[0]["id"]))
        res = supabase.table("msg_conversations").insert({
            "club_id": club_id, "type": "perso",
            "user_key1": user_key, "user_key2": pres_key,
        }).execute()
        if res.data:
            return redirect(url_for("messagerie_conv", conv_id=res.data[0]["id"]))
    except Exception:
        pass
    return redirect(url_for("messagerie"))


# ══════════════════════════════════════════════════════════════════════════════
#  Stripe — Abonnements
# ══════════════════════════════════════════════════════════════════════════════

def _stripe_configured():
    key = os.getenv("STRIPE_SECRET_KEY", "")
    return bool(key and not key.startswith("sk_test_REMPLACE"))


@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    if not _stripe_configured():
        flash("⚠️ Stripe n'est pas encore configuré. Renseigne tes clés dans le fichier .env", "error")
        return redirect(url_for("tarifs"))

    plan_cible = request.form.get("plan", "pro")  # "pro" ou "elite"
    if plan_cible == "elite":
        price_id = os.getenv("STRIPE_ELITE_PRICE_ID", "")
    else:
        plan_cible = "pro"
        price_id = os.getenv("STRIPE_PRICE_ID", "")

    if not price_id:
        flash(f"⚠️ Le tarif {plan_cible.capitalize()} n'est pas encore configuré (STRIPE_{'ELITE_' if plan_cible=='elite' else ''}PRICE_ID manquant).", "error")
        return redirect(url_for("tarifs"))

    club_id = session.get("club_id")
    res = supabase.table("clubs").select("email,stripe_customer_id").eq("id", club_id).execute()
    club = res.data[0] if res.data else {}

    try:
        kwargs = dict(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=url_for("checkout_succes", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("tarifs", _external=True),
            client_reference_id=club_id,
            metadata={"club_id": club_id, "plan_cible": plan_cible},
        )
        if club.get("stripe_customer_id"):
            kwargs["customer"] = club["stripe_customer_id"]
        else:
            kwargs["customer_email"] = club.get("email", "")

        cs = stripe.checkout.Session.create(**kwargs)
        return redirect(cs.url, code=303)

    except stripe.StripeError as e:
        flash(f"Erreur Stripe : {e.user_message or str(e)}", "error")
        return redirect(url_for("tarifs"))


@app.route("/checkout/succes")
@login_required
def checkout_succes():
    session_id   = request.args.get("session_id", "")
    plan_attribue = "pro"
    if session_id and _stripe_configured():
        try:
            cs = stripe.checkout.Session.retrieve(session_id)
            club_id       = cs.client_reference_id or cs.metadata.get("club_id")
            plan_attribue = cs.metadata.get("plan_cible", "pro")
            if club_id:
                supabase.table("clubs").update({
                    "plan":                   plan_attribue,
                    "stripe_customer_id":     cs.customer,
                    "stripe_subscription_id": cs.subscription,
                }).eq("id", club_id).execute()
                session["plan"] = plan_attribue
        except Exception:
            pass  # Le webhook prendra le relais

    nom_plan = "Elite 🚀" if plan_attribue == "elite" else "Pro ⚡"
    flash(f"🎉 Bienvenue dans le plan {nom_plan} ! Toutes les fonctionnalités sont débloquées.", "success")
    return redirect(url_for("dashboard"))


@app.route("/checkout/annule")
def checkout_annule():
    flash("Paiement annulé. Tu peux réessayer quand tu veux.", "error")
    return redirect(url_for("tarifs"))


@app.route("/webhook", methods=["POST"])
def webhook():
    """Webhook Stripe pour maintenir le plan à jour en temps réel."""
    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    secret     = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception:
        return "", 400

    etype = event["type"]
    obj   = event["data"]["object"]

    if etype == "checkout.session.completed":
        club_id      = obj.get("client_reference_id") or obj.get("metadata", {}).get("club_id")
        plan_cible   = obj.get("metadata", {}).get("plan_cible", "pro")
        if club_id:
            supabase.table("clubs").update({
                "plan":                   plan_cible,
                "stripe_customer_id":     obj.get("customer"),
                "stripe_subscription_id": obj.get("subscription"),
            }).eq("id", club_id).execute()

    elif etype in ("customer.subscription.deleted", "customer.subscription.paused"):
        customer_id = obj.get("customer")
        if customer_id:
            supabase.table("clubs").update({
                "plan": "gratuit",
                "stripe_subscription_id": None,
            }).eq("stripe_customer_id", customer_id).execute()

    elif etype == "invoice.payment_succeeded":
        # Renouvellement — on détecte le plan via le price_id de la subscription
        customer_id     = obj.get("customer")
        subscription_id = obj.get("subscription")
        if customer_id:
            plan_renouv = "pro"
            if subscription_id and _stripe_configured():
                try:
                    sub = stripe.Subscription.retrieve(subscription_id)
                    paid_price = sub["items"]["data"][0]["price"]["id"]
                    if paid_price == os.getenv("STRIPE_ELITE_PRICE_ID", "__none__"):
                        plan_renouv = "elite"
                except Exception:
                    pass
            supabase.table("clubs").update({"plan": plan_renouv}).eq("stripe_customer_id", customer_id).execute()

    return "", 200


@app.route("/gerer-abonnement")
@login_required
def gerer_abonnement():
    if not _stripe_configured():
        flash("⚠️ Stripe n'est pas encore configuré.", "error")
        return redirect(url_for("dashboard"))

    customer_id = session.get("stripe_customer_id")
    if not customer_id:
        # Tentative de récupération depuis la DB
        res = supabase.table("clubs").select("stripe_customer_id").eq("id", session.get("club_id")).execute()
        if res.data:
            customer_id = res.data[0].get("stripe_customer_id")

    if not customer_id:
        flash("Aucun abonnement actif trouvé.", "error")
        return redirect(url_for("dashboard"))

    try:
        portal = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=url_for("dashboard", _external=True),
        )
        return redirect(portal.url, code=303)
    except stripe.StripeError as e:
        flash(f"Erreur portail Stripe : {e.user_message or str(e)}", "error")
        return redirect(url_for("dashboard"))


# ══════════════════════════════════════════════════════════════════════════════
#  Déconnexion
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  Paramètres du club (logo + couleurs)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/parametres", methods=["GET", "POST"])
@coach_or_president
def parametres():
    club_id = session.get("club_id")

    if request.method == "POST":
        c1 = (request.form.get("couleur_principale") or "#E24B4A").strip()
        c2 = (request.form.get("couleur_secondaire") or "#378ADD").strip()
        data = {"couleur_principale": c1, "couleur_secondaire": c2}

        # Infos club
        nom_club_new = request.form.get("nom_club", "").strip()
        sport_new    = request.form.get("sport", "").strip()
        ville_new    = request.form.get("ville", "").strip()
        if nom_club_new:
            data["nom_club"] = nom_club_new
            session["nom_club"] = nom_club_new
        if sport_new:
            data["sport"] = sport_new
        if ville_new:
            data["ville"] = ville_new

        logo = request.files.get("logo")
        if logo and logo.filename:
            ext = logo.filename.rsplit(".", 1)[-1].lower()
            if ext in ("png", "jpg", "jpeg", "svg", "webp"):
                filename  = f"club_{club_id}.{ext}"
                file_bytes = logo.read()
                ct = logo.content_type or f"image/{ext}"
                # Supprimer les anciens logos
                for old_ext in ("png", "jpg", "jpeg", "svg", "webp"):
                    try:
                        supabase.storage.from_("logos").remove([f"club_{club_id}.{old_ext}"])
                    except Exception:
                        pass
                try:
                    supabase.storage.from_("logos").upload(
                        filename, file_bytes,
                        {"content-type": ct, "upsert": "true"}
                    )
                    logo_url = supabase.storage.from_("logos").get_public_url(filename)
                    data["logo_url"] = logo_url
                    session["logo_url"] = logo_url
                except Exception as ex:
                    flash(f"Erreur upload logo : {ex}", "error")
            else:
                flash("Format non supporté. Utilisez PNG, JPG, SVG ou WEBP.", "error")

        supabase.table("clubs").update(data).eq("id", club_id).execute()
        session["couleur_principale"] = c1
        session["couleur_secondaire"] = c2
        flash("Paramètres enregistrés avec succès.", "success")
        return redirect(url_for("parametres"))

    # GET
    res  = supabase.table("clubs").select("nom_club,sport,ville,logo_url,couleur_principale,couleur_secondaire").eq("id", club_id).execute()
    club = res.data[0] if res.data else {}
    return render_template("parametres.html",
        nom_club=club.get("nom_club") or session.get("nom_club", ""),
        sport=club.get("sport", "Football"),
        ville=club.get("ville", ""),
        logo_url=club.get("logo_url") or session.get("logo_url"),
        couleur_principale=club.get("couleur_principale") or session.get("couleur_principale", "#E24B4A"),
        couleur_secondaire=club.get("couleur_secondaire") or session.get("couleur_secondaire", "#378ADD"),
        sports_list=list(SPORT_VOCAB.keys()),
    )


@app.route("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("connexion"))


# ══════════════════════════════════════════════════════════════════════════════
#  Analytics — Plan Elite
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/analytics")
@coach_or_president
@elite_required
def analytics():
    club_id = session.get("club_id")
    sport   = _get_sport(club_id)

    # Matchs joués (avec score)
    try:
        mr = supabase.table("matchs").select("*")\
                     .eq("club_id", club_id)\
                     .not_.is_("score_nous", "null")\
                     .order("date_match").execute()
        matchs = mr.data or []
    except Exception:
        matchs = []

    # Effectif
    try:
        er = supabase.table("joueurs").select("id,prenom,nom,poste,forme_note")\
                     .eq("club_id", club_id).order("nom").execute()
        effectif = er.data or []
    except Exception:
        effectif = []

    # Stats joueurs
    try:
        sr = supabase.table("stats_joueurs").select("joueur_id,stats")\
                     .eq("club_id", club_id).execute()
        stats_raw = sr.data or []
    except Exception:
        stats_raw = []

    # Agrégation stats par joueur
    stats_by_joueur = {}
    for row in stats_raw:
        jid  = str(row.get("joueur_id", ""))
        sobj = row.get("stats") or {}
        if jid not in stats_by_joueur:
            stats_by_joueur[jid] = {}
        for k, v in sobj.items():
            try:
                stats_by_joueur[jid][k] = stats_by_joueur[jid].get(k, 0) + int(v or 0)
            except (ValueError, TypeError):
                pass

    # Données graphique résultats
    chart_matchs = []
    victoires = defaites = nuls = 0
    for m in matchs:
        sn, se = m.get("score_nous"), m.get("score_eux")
        if sn is None or se is None:
            continue
        res = "V" if sn > se else ("N" if sn == se else "D")
        if res == "V": victoires += 1
        elif res == "D": defaites += 1
        else: nuls += 1
        chart_matchs.append({
            "date":      m.get("date_match", "")[:10],
            "label":     f"vs {m.get('adversaire','')}",
            "score_nous": sn,
            "score_eux":  se,
            "result":     res,
        })

    # Labels stats selon sport
    stat_fields = MATCH_STATS_FIELDS.get(sport, [])
    first_field = stat_fields[0][0] if stat_fields else "buts"
    first_label = stat_fields[0][1] if stat_fields else "Buts"

    # Top 5 par premier champ de stats
    top_joueurs = []
    for j in effectif:
        jid   = str(j.get("id", ""))
        total = stats_by_joueur.get(jid, {}).get(first_field, 0)
        if total > 0:
            top_joueurs.append({"nom": f"{j.get('prenom','')} {j.get('nom','')}", "val": total, "poste": j.get("poste","")})
    top_joueurs.sort(key=lambda x: x["val"], reverse=True)
    top_joueurs = top_joueurs[:8]

    return render_template("analytics.html",
        sport=sport,
        matchs=matchs,
        chart_matchs=chart_matchs,
        effectif=effectif,
        stats_by_joueur=stats_by_joueur,
        stat_fields=stat_fields,
        first_field=first_field,
        first_label=first_label,
        top_joueurs=top_joueurs,
        victoires=victoires,
        defaites=defaites,
        nuls=nuls,
    )


# ── Email convocations (Elite) ─────────────────────────────────────────────────

@app.route("/convocations/<match_id>/envoyer-email", methods=["POST"])
@coach_or_president
@elite_required
def envoyer_convocations_email(match_id):
    club_id = session.get("club_id")
    nom_club = session.get("nom_club", "Votre club")

    if not _MAIL_AVAILABLE or not app.config.get("MAIL_USERNAME"):
        flash("⚠️ La configuration email (MAIL_USERNAME / MAIL_PASSWORD) n'est pas renseignée dans le .env.", "error")
        return redirect(request.referrer or url_for("matchs"))

    # Récupérer le match
    try:
        mr = supabase.table("matchs").select("date_match,adversaire,domicile")\
                     .eq("id", match_id).eq("club_id", club_id).execute()
        match = mr.data[0] if mr.data else None
    except Exception:
        match = None

    if not match:
        flash("Match introuvable.", "error")
        return redirect(url_for("matchs"))

    # Récupérer les convocations
    try:
        cr = supabase.table("convocations").select("joueur_id,statut")\
                     .eq("match_id", match_id).eq("club_id", club_id).execute()
        convocations = cr.data or []
    except Exception:
        convocations = []

    if not convocations:
        flash("Aucune convocation enregistrée pour ce match.", "error")
        return redirect(url_for("matchs"))

    # Récupérer emails des joueurs convoqués
    joueur_ids = [str(c["joueur_id"]) for c in convocations]
    try:
        jr = supabase.table("joueurs").select("id,prenom,nom,email")\
                     .eq("club_id", club_id).execute()
        joueurs_map = {str(j["id"]): j for j in (jr.data or [])}
    except Exception:
        joueurs_map = {}

    date_str    = match.get("date_match", "")[:10]
    adversaire  = match.get("adversaire", "")
    lieu        = "à domicile" if match.get("domicile") else "à l'extérieur"
    envoyes     = 0
    erreurs     = 0

    for conv in convocations:
        jid  = str(conv.get("joueur_id", ""))
        j    = joueurs_map.get(jid, {})
        email_dest = j.get("email", "")
        if not email_dest:
            continue
        statut_label = {"titulaire_pressenti": "titulaire pressenti", "remplacant": "remplaçant", "convoque": "convoqué"}.get(conv.get("statut", ""), "convoqué")
        try:
            msg = MailMessage(
                subject=f"[{nom_club}] Convocation — Match vs {adversaire} le {date_str}",
                recipients=[email_dest],
                html=f"""
                <div style="font-family:sans-serif;max-width:480px;margin:auto;">
                  <div style="background:#0D0D18;padding:1.5rem;border-radius:8px 8px 0 0;text-align:center;">
                    <span style="color:#fff;font-size:1.1rem;font-weight:700;">⚽ {nom_club}</span>
                  </div>
                  <div style="padding:1.5rem;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
                    <h2 style="margin:0 0 1rem;font-size:1rem;">Bonjour {j.get('prenom','')},</h2>
                    <p>Tu es <strong>{statut_label}</strong> pour le match suivant :</p>
                    <div style="background:#f4f5f7;border-radius:6px;padding:1rem;margin:1rem 0;">
                      <div>🏟 <strong>vs {adversaire}</strong> — {lieu}</div>
                      <div>📅 {date_str}</div>
                    </div>
                    <p style="color:#6b7280;font-size:.85rem;">Réponds dès que possible si tu as une indisponibilité.</p>
                    <hr style="border:none;border-top:1px solid #e5e7eb;margin:1rem 0;">
                    <p style="color:#9ca3af;font-size:.75rem;">Tactix · Application de gestion sportive</p>
                  </div>
                </div>""",
            )
            mail.send(msg)
            envoyes += 1
        except Exception:
            erreurs += 1

    if envoyes:
        flash(f"✉️ {envoyes} email{'s' if envoyes > 1 else ''} envoyé{'s' if envoyes > 1 else ''} avec succès.", "success")
    if erreurs:
        flash(f"⚠️ {erreurs} email{'s' if erreurs > 1 else ''} n'ont pas pu être envoyé{'s' if erreurs > 1 else ''} (joueurs sans email ?)", "error")

    return redirect(url_for("matchs"))


if __name__ == "__main__":
    app.run(debug=True)
