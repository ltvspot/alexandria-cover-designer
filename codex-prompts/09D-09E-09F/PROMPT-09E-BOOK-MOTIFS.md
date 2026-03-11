# PROMPT-09E — Book-Specific Visual Motifs for All 99 Books

## Overview

This prompt adds specific `BookMotif` entries for every book in the Alexandria catalog that currently falls through to the generic fallback. After this change, all 99 books will produce unique, recognisable cover illustrations instead of near-identical romantic-couple scenes.

---

## The Problem

Currently `_motif_for_book()` in `src/prompt_generator.py` has specific entries for only ~25 books. Every other title hits the final generic fallback:

```python
return BookMotif(
    iconic_scene="pivotal narrative tableau with period costume, emotional tension, and dramatic environmental storytelling",
    character_portrait="central protagonist in historically grounded attire, expressive face, and purposeful posture",
    ...
)
```

This produces nearly identical compositions — typically a romanticised period couple — regardless of whether the book is a Rabelaisian comedy, a Philippine revolution novel, or a Cold War sci-fi story.

---

## Changes Required

### File: `src/prompt_generator.py`

Add the following entries to the `_motif_for_book()` function **BEFORE the author-fallback blocks** (before the `if "austen" in author:` line, currently around line 604) and **BEFORE the final generic `return` statement**.

Each entry uses `title_author`, the lowercased, punctuation-stripped concatenation of title and author produced by `_normalize()`.

---

```python
    # ── A Room with a View ─────────────────────────────────────────────────
    if "room with a view" in title_author:
        return BookMotif(
            iconic_scene="Edwardian English tourists at a pensione window overlooking the Arno river with Florentine domes and cypress hills",
            character_portrait="young Englishwoman in white muslin leaning from an open window above terracotta rooftops and the river Arno",
            setting_landscape="sun-drenched Florentine hillside terrace, olive groves, ochre villas, and a shimmering Arno valley below",
            dramatic_moment="spontaneous kiss in a golden Italian wheat field as Edwardian propriety crumbles under Tuscan sun",
            symbolic_theme="liberation from repression shown by an open shuttered window framing Florence's sky against a closed English parlour",
            style_specific_prefix="Edwardian watercolour travel illustration",
        )

    # ── Gulliver's Travels ─────────────────────────────────────────────
    if "gulliver" in title_author:
        return BookMotif(
            iconic_scene="giant human pinned to a beach by hundreds of tiny ropes while Lilliputian soldiers swarm his body",
            character_portrait="bemused giant ship's surgeon flat on a sunlit strand, bound by thread-fine ropes, tiny armies at his cuffs",
            setting_landscape="miniature Lilliputian city of delicate spires and streets stretching beneath a stranded giant's coat",
            dramatic_moment="voyage to Laputa as the floating island's shadow darkens a fleet below and scholars peer from cloud-level windows",
            symbolic_theme="human arrogance satirised by a colossus helpless in a nation of thumb-sized rulers wielding needle swords",
            style_specific_prefix="satirical Georgian copperplate engraving",
        )

    # ── Emma ─────────────────────────────────────────────────────
    if " emma " in f" {title} " or title.startswith("emma"):
        return BookMotif(
            iconic_scene="self-assured young matchmaker surveying Highbury village from a sunlit drawing room window with tea and embroidery",
            character_portrait="confident Regency gentlewoman at a writing desk, quill in hand, scheming smile, afternoon light on silk dress",
            setting_landscape="prosperous English village green, Hartfield gardens, stone church tower, and neat hedgerows in warm summer",
            dramatic_moment="sudden mortifying picnic on Box Hill as careless wit wounds a gentle companion before all of society",
            symbolic_theme="self-deception unravelled by mismatched silhouettes on a village green under clearing clouds",
            style_specific_prefix="Regency pastoral watercolour etching",
        )

    # ── A Modest Proposal ──────────────────────────────────────────────
    if "modest proposal" in title_author:
        return BookMotif(
            iconic_scene="Georgian pamphlet illustration of gaunt Irish children and well-fed English landlords at a banquet table",
            character_portrait="sardonic pamphleteer in Georgian wig gesturing toward a ledger of infant statistics with bitter calm",
            setting_landscape="bleak Georgian Dublin streets, starving families by doorways, cattle market pennants above cobblestones",
            dramatic_moment="absurd proposal read aloud to powdered aristocrats who nod approvingly over a silver dining service",
            symbolic_theme="institutional cruelty masked as philanthropy shown by a roast silver platter bearing an infant's bonnet",
            style_specific_prefix="dark satirical Georgian broadside woodcut",
        )

    # ── The Mysterious Stranger ────────────────────────────────────────────
    if "mysterious stranger" in title_author:
        return BookMotif(
            iconic_scene="a beautiful young stranger with supernatural calm conjures miniature human figures in a medieval Austrian village square",
            character_portrait="elegant pale youth with otherworldly eyes shaping tiny clay people with indifferent grace in firelight",
            setting_landscape="medieval Austrian hilltop village, cobbled lanes, a church steeple, and perpetual twilight over forested valleys",
            dramatic_moment="stranger sweeping away his miniature village with one hand as boys watch in existential horror",
            symbolic_theme="divine indifference illustrated by a god-figure crushing a perfect tiny world between thumb and finger",
            style_specific_prefix="dark Romantic expressionist woodcut",
        )

    # ── Right Ho, Jeeves ───────────────────────────────────────────────
    if "right ho jeeves" in title_author or ("jeeves" in title_author and "right ho" in title_author):
        return BookMotif(
            iconic_scene="bumbling English aristocrat sprawled in a deck chair at Brinkley Court while an immaculate valet surveys the chaos",
            character_portrait="genial young gentleman in white flannel suit, straw boater askew, look of cheerful bewilderment",
            setting_landscape="lush Worcestershire country house lawns, rose borders, croquet hoops, and a long gravel drive at summer noon",
            dramatic_moment="disastrous fancy-dress dinner erupting into social catastrophe as Jeeves stands serenely at the sideboard",
            symbolic_theme="class comedy shown by a butler's perfectly pressed gloves beside a crumpled master's panama hat",
            style_specific_prefix="Edwardian comic illustration watercolour",
        )

    # ── The Enchanted April ──────────────────────────────────────────────
    if "enchanted april" in title_author:
        return BookMotif(
            iconic_scene="four English women in a medieval Italian castle garden awash with wisteria, bougainvillea, and spring sea light",
            character_portrait="reserved English gentlewoman transformed, arms open on a Mediterranean castle terrace, sun on her upturned face",
            setting_landscape="terraced San Salvatore castle above a shimmering Ligurian bay, stone walls dripping with jasmine and wisteria",
            dramatic_moment="first morning when each woman steps into the Italian garden and feels the enchantment dissolve English reserve",
            symbolic_theme="emotional rebirth shown by an English grey coat shed at the gate of a blossom-drenched Mediterranean garden",
            style_specific_prefix="Edwardian Mediterranean watercolour idyll",
        )

    # ── Cranford ─────────────────────────────────────────────────────
    if "cranford" in title_author:
        return BookMotif(
            iconic_scene="genteel elderly ladies taking tea in a modest parlour, fine china and faded lace, Victorian social ritual",
            character_portrait="dignified older Englishwoman in Victorian cap and shawl, erect posture, gentle authority in a small drawing room",
            setting_landscape="quiet English market town, neat brick cottages, a high street with a draper's bow window and gas lamp",
            dramatic_moment="unexpected railway arrival disrupting Cranford's tranquil order as modern England presses at the hedgerow",
            symbolic_theme="graceful decline shown by a chipped teacup beside a sealed letter on a fading floral tablecloth",
            style_specific_prefix="Victorian domestic genre engraving",
        )

    # ── Expedition of Humphry Clinker ────────────────────────────────────
    if "humphry clinker" in title_author:
        return BookMotif(
            iconic_scene="a motley English family party in a jolting coach careening through 18th-century Scottish highland roads",
            character_portrait="irascible Welsh squire in travelling clothes, apoplectic expression, bouncing in a mud-spattered post-chaise",
            setting_landscape="rolling 18th-century British countryside, Roman baths, Edinburgh closes, and Highland mountain passes",
            dramatic_moment="chaotic ford crossing where the coach sinks and passengers scramble to muddy riverbanks in full comedy",
            symbolic_theme="national character exposed by comic journey shown as a patchwork travelling bag spilling across a map of Britain",
            style_specific_prefix="Georgian picaresque caricature engraving",
        )

    # ── History of Tom Jones ─────────────────────────────────────────────
    if "tom jones" in title_author:
        return BookMotif(
            iconic_scene="handsome foundling in Georgian hunting attire striding through English countryside toward a manor house at dawn",
            character_portrait="open-faced young man in 18th-century coat, honest expression, walking stick, fields and distant hall behind",
            setting_landscape="rolling Georgian England, Squire Western's park, inn courtyards, London coaching roads, and open meadows",
            dramatic_moment="confrontation in a London drawing room as true identity is revealed before assembled Georgian society",
            symbolic_theme="good nature triumphing over class shown by a foundling's token beside a broken aristocratic seal",
            style_specific_prefix="Georgian narrative engraving pastoral",
        )

    # ── The Pickwick Papers ────────────────────────────────────────────
    if "pickwick" in title_author:
        return BookMotif(
            iconic_scene="portly bespectacled gentleman and three loyal companions boarding a coach outside a Georgian inn at dawn",
            character_portrait="round benevolent gentleman in tights and gaiters, beaming smile, tasselled hat, notebooks under arm",
            setting_landscape="coaching-inn yard, Dingley Dell snowscape, Fleet Prison courtyard, and bustling Victorian London streets",
            dramatic_moment="Mr Pickwick's chaotic ice-skating expedition ending in a snowdrift to universal hilarity",
            symbolic_theme="innocent optimism shown by a magnifying glass and a notebook over a tangled map of English roads",
            style_specific_prefix="Victorian comic engraving Dickensian",
        )

    # ── The Wind in the Willows ──────────────────────────────────────────
    if "wind in the willows" in title_author:
        return BookMotif(
            iconic_scene="Mole, Rat, and Badger picnicking on the river bank while Toad Hall rises through weeping willows behind",
            character_portrait="cheerful Mole in his velvet waistcoat beside Rat with a rowing hamper on the sunlit Thames bank",
            setting_landscape="the gentle River Bank with osiers, water-meadows, and Toad Hall's chimneys visible through summer willow curtains",
            dramatic_moment="Mr Toad in racing goggles at the wheel of a motor car careening down a country lane in ecstatic speed",
            symbolic_theme="home and friendship shown by four animal silhouettes at a lantern-lit burrow door in a winter snowfield",
            style_specific_prefix="Edwardian pastoral watercolour illustration",
        )

    # ── Middlemarch ────────────────────────────────────────────────────
    if "middlemarch" in title_author:
        return BookMotif(
            iconic_scene="idealistic young gentlewoman in black riding dress surveys a provincial English town from a hilltop at sunrise",
            character_portrait="earnest Victorian woman with thoughtful eyes, dark dress, an open book, and reform documents on her desk",
            setting_landscape="Midlands market town, brick hospital under construction, Casaubon's library, and fog-softened fields",
            dramatic_moment="Dorothea's torchlit renunciation of fortune in a grey dawn as rain runs down tall rectory windows",
            symbolic_theme="thwarted idealism shown by an extinguished torch before an unfinished reform map and a locked casket",
            style_specific_prefix="Victorian realist oil-engraving hybrid",
        )

    # ── The Lady with the Dog ──────────────────────────────────────────
    if "lady with the dog" in title_author or "lady with a dog" in title_author:
        return BookMotif(
            iconic_scene="solitary woman with a white Pomeranian on the Yalta promenade as grey sea meets overcast sky",
            character_portrait="pale melancholy woman in a light summer dress and hat, small dog on leash, eyes fixed on the Black Sea",
            setting_landscape="Yalta promenade, acacia trees, white hotels above a calm sea, afternoon light fading on resort parasols",
            dramatic_moment="first silent meeting on the embankment as sea mist rolls in and a watermelon slice sits untouched",
            symbolic_theme="illicit longing shown by two separate shadows converging on a Yalta seafront in winter fog",
            style_specific_prefix="melancholy Russian Impressionist plein-air",
        )

    # ── The Lady of the Lake ───────────────────────────────────────────
    if "lady of the lake" in title_author:
        return BookMotif(
            iconic_scene="a warrior's horn call echoing across a Highland loch as a woman glides toward shore in a birch-bark skiff",
            character_portrait="Ellen Douglas in white robe at the prow of a small boat, misty loch and craggy island peak behind her",
            setting_landscape="Ben Venue's rocky reflection in a dawn loch, heather shores, pine forest, and morning mist rising",
            dramatic_moment="Highland chieftain and hidden king in disguise face off on a misty island as Ellen watches from a crag",
            symbolic_theme="highland loyalty shown by a claymore laid at the feet of a woman on an island in morning mist",
            style_specific_prefix="Romantic Scottish landscape engraving",
        )

    # ── The Satyricon ────────────────────────────────────────────────────
    if "satyricon" in title_author:
        return BookMotif(
            iconic_scene="Trimalchio's banquet hall erupting with roast peacocks, acrobats, wine fountains, and guests in gold-trimmed togas",
            character_portrait="wealthy freedman in extravagant purple robes presiding over his own mock-funeral feast among slavering guests",
            setting_landscape="ancient Roman triclinium dripping with garlands, exotic birds in gilded cages, mosaic floors, and amphorae",
            dramatic_moment="skeleton automaton carried in at the feast as drunk guests recoil from mortality hidden beneath the revelry",
            symbolic_theme="Roman excess embodied by a gold skeleton toasting with a brimming goblet over an overturned world",
            style_specific_prefix="decadent Roman mosaic fresco style",
        )

    # ── Little Women ───────────────────────────────────────────────────
    if "little women" in title_author:
        return BookMotif(
            iconic_scene="four March sisters gathered around a hearth in a Civil War-era New England parlour, sewing, reading, and laughing",
            character_portrait="spirited tomboy in ink-stained fingers and chestnut hair at a writing desk, manuscript pages around her",
            setting_landscape="warm New England cottage in winter snow, evergreen wreath on the door, amber lamplight in frosted windows",
            dramatic_moment="Beth's piano playing filling the parlour as the family waits for news from the front in hushed candlelight",
            symbolic_theme="sisterhood shown by four pairs of hands clasped over a worn family Bible beside a Christmas stocking",
            style_specific_prefix="Civil War-era domestic narrative engraving",
        )

    # ── The Eyes Have It ───────────────────────────────────────────────
    if "eyes have it" in title_author:
        return BookMotif(
            iconic_scene="paranoid commuter in a 1950s train carriage scrutinising fellow passengers' eyes for alien telltale signs",
            character_portrait="tense suburban man gripping a newspaper, sweating, watching eyes in a crowded mid-century rail carriage",
            setting_landscape="bland 1950s American suburbs, identical houses, commuter trains, and eyes that never look quite right",
            dramatic_moment="protagonist's dawning realisation that every passenger in the car has detachable eyes on short stalks",
            symbolic_theme="Cold War paranoia shown by a field of mismatched glass eyes staring from a newspaper's grey columns",
            style_specific_prefix="1950s pulp sci-fi ink halftone illustration",
        )

    # ── Laughter: An Essay on the Meaning of the Comic ─────────────────────
    if "laughter" in title_author and "bergson" in title_author:
        return BookMotif(
            iconic_scene="a theatre stage where mechanical marionettes laugh and weep identically, actors frozen mid-gesture like wound-up toys",
            character_portrait="philosopher in a frock coat studying two masks — comedy and tragedy — reflected in a cracked mirror",
            setting_landscape="a commedia dell'arte stage with raked boards, footlights, and an audience of identical blank-faced spectators",
            dramatic_moment="jack-in-the-box moment as a dignified gentleman slips on ice and an audience bursts into simultaneous laughter",
            symbolic_theme="automatism in life shown by a clockwork figure in a frock coat miming a human's most solemn gestures",
            style_specific_prefix="Belle Époque philosophical allegorical engraving",
        )

    # ── Eve's Diary ────────────────────────────────────────────────────
    if "eve s diary" in title_author or "eves diary" in title_author:
        return BookMotif(
            iconic_scene="first woman in paradise writing in a journal amid cascading flowers, curious animals gathering to look",
            character_portrait="wide-eyed Eve in Eden, garland of flowers in her hair, kneeling to examine a butterfly on her finger",
            setting_landscape="lush Garden of Eden with waterfalls, tropical blossoms, peacocks, and an amber sunset over paradise hills",
            dramatic_moment="Eve's first encounter with fire, prodding glowing embers with a branch as Adam watches from a distance",
            symbolic_theme="wonder and naming shown by Eve holding an apple up to sunlight as every creature of Eden watches",
            style_specific_prefix="Edenic Pre-Raphaelite botanical illustration",
        )

    # ── The Sky Trap ───────────────────────────────────────────────────
    if "sky trap" in title_author:
        return BookMotif(
            iconic_scene="a biplane circling helplessly against an invisible ceiling barrier as the sky glows with a strange shimmering membrane",
            character_portrait="goggled aviator in open cockpit, hammering against invisible resistance above cloud tops, face stricken",
            setting_landscape="bright blue sky suddenly terminated by a shimmering translucent ceiling above towering cumulus clouds",
            dramatic_moment="pilot pushing throttle to full as the plane strains against the invisible barrier and instruments spin wildly",
            symbolic_theme="human freedom caged shown by a bird and biplane both pressing against an unseen crystal dome in clear sky",
            style_specific_prefix="1930s pulp adventure aviation illustration",
        )

    # ── The Blue Castle ──────────────────────────────────────────────────
    if "blue castle" in title_author:
        return BookMotif(
            iconic_scene="a repressed woman finally free, laughing in a canoe on a Muskoka wilderness lake under a wide Canadian sky",
            character_portrait="liberated young woman, red cheeks, windswept hair, paddling a birchbark canoe among pine-lined islands",
            setting_landscape="Ontario Muskoka lake at sunset, granite outcroppings, dark pine reflections, and a log cabin on the shore",
            dramatic_moment="Valancy walking out of her aunt's Victorian parlour for the last time, door swinging behind her in spring air",
            symbolic_theme="liberation from convention shown by an open birdcage on a Victorian windowsill above a wide wilderness lake",
            style_specific_prefix="Canadian wilderness watercolour lyric",
        )

    # ── Adventures of Ferdinand Count Fathom ──────────────────────────────
    if "ferdinand count fathom" in title_author or "count fathom" in title_author:
        return BookMotif(
            iconic_scene="charming villain in powdered wig and silk coat bowing to a trusting noblewoman in a candlelit European salon",
            character_portrait="handsome rakish schemer in 18th-century court dress, practised smile hiding cold calculation",
            setting_landscape="gilded European drawing rooms, Vienna streets, London gaming dens, and moonlit forest highway ambush",
            dramatic_moment="Count Fathom cornered at sword point in a midnight forest inn as his web of deceptions collapses",
            symbolic_theme="villainy unmasked shown by a lace handkerchief concealing a dagger beside a forged letter of nobility",
            style_specific_prefix="Georgian picaresque villain engraving",
        )

    # ── Three Men in a Boat ─────────────────────────────────────────────
    if "three men in a boat" in title_author:
        return BookMotif(
            iconic_scene="three hapless friends and a fox terrier crammed in a rowboat on the Thames, one struggling with a tin opener",
            character_portrait="three moustachioed late-Victorian men in straw boaters and blazers looking baffled at a tangled camping tarpaulin",
            setting_landscape="tranquil upper Thames, willow-fringed banks, lock gates, riverside pubs, and a misty morning on the water",
            dramatic_moment="tent collapsing in the rain on a Thames island as the dog sits smug and dry in the upturned boat",
            symbolic_theme="comic English stoicism shown by three sodden figures toasting disaster with tin mugs in a downpour",
            style_specific_prefix="Victorian comic illustration pen-and-ink",
        )

    # ── A Doll's House ───────────────────────────────────────────────────
    if "doll s house" in title_author or "dolls house" in title_author or "a doll" in title_author:
        return BookMotif(
            iconic_scene="a woman in Victorian parlour dress rising from a perfect bourgeois Christmas Eve interior toward a door",
            character_portrait="Nora Helmer in party dress, coat in hand, resolute face turned from a glittering Christmas tree",
            setting_landscape="Ibsenian Norwegian Victorian parlour, Christmas garlands, a letter box, gas lamp, snow beyond frosted panes",
            dramatic_moment="the slamming door echoing through a silent stage as the audience absorbs the finality of Nora's departure",
            symbolic_theme="liberation shown by an empty doll's house interior with a swinging front door and scattered macaroons",
            style_specific_prefix="Nordic Symbolist theatre engraving",
        )

    # ── Adventures of Roderick Random ───────────────────────────────────
    if "roderick random" in title_author:
        return BookMotif(
            iconic_scene="young Scottish adventurer on a 18th-century man-of-war deck during a naval battle with smoke and cannon fire",
            character_portrait="raw young Scot in naval surgeon's mate coat, sharp determined eyes, sea spray on his face and coat collar",
            setting_landscape="Georgian naval warship under full sail, tropical port taverns, London coaching roads, and Scottish moorland",
            dramatic_moment="flogged on deck then cast ashore as a Spanish fleet appears on the horizon and smoke billows from cannon ports",
            symbolic_theme="fortune's wheel shown by a naval surgeon's case and a Highland dirk beside a spinning globe on a chart",
            style_specific_prefix="18th-century naval adventure engraving",
        )

    # ── Adventures of Tom Sawyer ─────────────────────────────────────────
    if "tom sawyer" in title_author:
        return BookMotif(
            iconic_scene="mischievous boy supervising friends whitewashing a long picket fence on a sunny Missouri morning",
            character_portrait="barefoot boy in patched trousers and straw hat, grin on his face, paintbrush in hand outside a fence",
            setting_landscape="Mississippi river town, white clapboard church, river bluffs, a steamboat on the brown current",
            dramatic_moment="Tom and Becky lost in McDougal's Cave as a candle gutters, Injun Joe's shadow on the cavern wall",
            symbolic_theme="boyhood freedom shown by a raft at the grassy bank of a wide river under a cloudless sky",
            style_specific_prefix="Americana Mississippi pastoral engraving",
        )

    # ── Twenty Years After ───────────────────────────────────────────────
    if "twenty years after" in title_author:
        return BookMotif(
            iconic_scene="four ageing musketeers reunited on horseback in Fronde-era Paris, swords drawn, loyalty undiminished by years",
            character_portrait="veteran swordsman in plain grey cloak, grey at the temples, still commanding on a battle-scarred charger",
            setting_landscape="Paris barricades of the Fronde, St Germain's lanes, English scaffold at Whitehall, and French countryside",
            dramatic_moment="Athos, Porthos, Aramis, and d'Artagnan breaking through a Paris gate at a gallop under flintlock fire",
            symbolic_theme="enduring brotherhood shown by four crossed swords forming a star above an hourglass leaking silver sand",
            style_specific_prefix="Baroque swashbuckling oil painting engraving",
        )

    # ── Lady Chatterley's Lover ───────────────────────────────────────────
    if "lady chatterley" in title_author or "chatterley" in title_author:
        return BookMotif(
            iconic_scene="a woman in summer dress walking through an ancient English woodland toward a gamekeeper's stone cottage",
            character_portrait="Connie Chatterley barefoot on a mossy path, sunlight filtering through oaks, Wragby Hall smokestacks behind",
            setting_landscape="ancient Nottinghamshire forest in spring, bluebells under oak canopy, colliery smoke beyond the treeline",
            dramatic_moment="rain falling through woodland as two figures shelter together in the keeper's hut, industrial England forgotten",
            symbolic_theme="natural passion against mechanised England shown by a bluebell breaking through coal-ash beside iron gates",
            style_specific_prefix="English pastoral Impressionist oil study",
        )

    # ── She Stoops to Conquer ────────────────────────────────────────────
    if "she stoops to conquer" in title_author:
        return BookMotif(
            iconic_scene="young gentleman mistaking a Georgian country manor for an inn, ordering servants about in comic confusion",
            character_portrait="spirited young woman in servant's apron over silk dress, suppressing laughter at a bewildered suitor",
            setting_landscape="Georgian English country house, horse paddock, a stone inn sign, and a moonlit park in 18th-century style",
            dramatic_moment="masked ball revelation in the garden as every identity is exposed under Chinese lanterns at the manor house",
            symbolic_theme="disguise and social comedy shown by a lady's fan laid beside a servant's mop on a Georgian parlour table",
            style_specific_prefix="Georgian comedy of manners engraving",
        )

    # ── Der Struwwelpeter ───────────────────────────────────────────────
    if "struwwelpeter" in title_author or "struwwel" in title_author:
        return BookMotif(
            iconic_scene="wild-haired boy with yard-long overgrown fingernails displayed on a plinth while gentlemen point in horror",
            character_portrait="Shock-headed Peter standing on a pedestal, towering matted hair, grotesquely long curling fingernails",
            setting_landscape="German bourgeois nursery with embroidered curtains, a spinning top, and a threatening tailor lurking outside",
            dramatic_moment="the great long red-legged scissor-man snipping a thumb-sucking child's fingers off in mid-air",
            symbolic_theme="disobedience punished in lurid moralising colours of black, red, and nursery yellow",
            style_specific_prefix="German Victorian cautionary tale woodcut illustration",
        )

    # ── The History of John Bull ───────────────────────────────────────────
    if "john bull" in title_author:
        return BookMotif(
            iconic_scene="a stout plain Englishman in farmer's coat haggling in a courtroom with allegorical figures of France, Holland, and Scotland",
            character_portrait="John Bull in broad-brimmed hat, beef-red face, stocky frame, clutching a ledger against legal tricksters",
            setting_landscape="18th-century English law courts, tavern parlours, Parliament's exterior, and a Channel port in grey weather",
            dramatic_moment="John Bull tearing up a bogus treaty in front of a disguised lawyer as national allegories grin in defeat",
            symbolic_theme="bluff English common sense against continental scheming shown by a roast beef plate outweighing a stack of treaties",
            style_specific_prefix="Georgian political allegory broadside",
        )

    # ── The Reign of Greed ──────────────────────────────────────────────
    if "reign of greed" in title_author:
        return BookMotif(
            iconic_scene="Filipino revolutionaries raising a torch in a tropical Manila square under Spanish colonial church towers at night",
            character_portrait="young Filipino idealist in barong tagalog, fierce eyes, clenched fist, a colonial rifle trained on him",
            setting_landscape="Spanish colonial Manila, Intramuros stone walls, tropical palms, Pasig river, and lantern-lit plazas",
            dramatic_moment="public execution in plaza de armas as the crowd holds its breath and a church bell tolls at dawn",
            symbolic_theme="colonial greed shown by golden chains binding tropical flowers to a stone colonial cross at sunrise",
            style_specific_prefix="late-19th-century Philippine revolutionary realism",
        )

    # ── Anthem ────────────────────────────────────────────────────────
    if "anthem" in title_author and "rand" in title_author:
        return BookMotif(
            iconic_scene="a lone figure in a grey collective uniform holds a glowing electric bulb aloft in a dark tunnel, forbidden light",
            character_portrait="solitary young man in numbered tunic, defiant upturned face, bare electric filament blazing in his hand",
            setting_landscape="subterranean tunnel beneath a collectivist city, crumbling rails, rubble, and a tiny stolen circle of light",
            dramatic_moment="Equality 7-2521 and Liberty 5-3000 fleeing into forbidden forest as the collectivist city's alarm bells ring",
            symbolic_theme="individual spark shown by a single lit bulb casting a long shadow against a wall of uniform grey stone",
            style_specific_prefix="dystopian constructivist allegory engraving",
        )

    # ── Là-bas ───────────────────────────────────────────────────────────
    if "l bas" in title_author or "la bas" in title_author or "huysmans" in title_author:
        return BookMotif(
            iconic_scene="decadent Parisian writer in candlelit study researching Satanism amid grimoires, skulls, and black candles",
            character_portrait="pale obsessive scholar surrounded by occult manuscripts, black altar candles, and medieval Gilles de Rais sketches",
            setting_landscape="fin-de-siècle Paris attic, Notre Dame spires through rain-black glass, a black mass chamber in the cellar",
            dramatic_moment="secret Satanic ritual in a Paris cellar as incense smoke and inverted candles surround hooded figures",
            symbolic_theme="spiritual decadence shown by a medieval knight's gauntlet grasping a black candle over an inverted cross",
            style_specific_prefix="Symbolist Decadent occult engraving",
        )

    # ── 2 B R 0 2 B ───────────────────────────────────────────────────
    if "2 b r 0 2 b" in title_author or "vonnegut" in title_author and "2br02b" in title_author.replace(" ", ""):
        return BookMotif(
            iconic_scene="a sterile futuristic waiting room where a man faces a choice between a newborn's life and an old man's death",
            character_portrait="haggard father in a hygienic future hospital, three birth certificates in hand, a gas chamber phone before him",
            setting_landscape="clinical white future hospital corridor, world population counter on the wall, a flower mural, and a dial phone",
            dramatic_moment="man pressing the government dial as the mural painter watches in silent horror and the counter ticks over",
            symbolic_theme="population as arithmetic shown by an hourglass balanced on birth and death certificates under fluorescent light",
            style_specific_prefix="1960s dystopian satirical illustration",
        )

    # ── The Man from Time ────────────────────────────────────────────────
    if "man from time" in title_author:
        return BookMotif(
            iconic_scene="a stranger in futuristic attire materialising in a 1950s street, anachronistic technology sparking in his hands",
            character_portrait="temporal traveller in sleek future garments, dazed expression, holding a glowing device in a mid-century city",
            setting_landscape="1950s American city, neon signs, chrome bumpers, and a shimmering temporal rift in the sky above a diner",
            dramatic_moment="time traveller cornered by 1950s policemen as his chronometer shorts out and the time rift begins to close",
            symbolic_theme="temporal displacement shown by a wristwatch with overlapping clock faces above a fragmented calendar",
            style_specific_prefix="1950s pulp science fiction ink illustration",
        )

    # ── The Vibration Wasps ──────────────────────────────────────────────
    if "vibration wasps" in title_author:
        return BookMotif(
            iconic_scene="enormous buzzing wasp creatures with vibrating crystalline wings hovering over a terrified mid-century town",
            character_portrait="scientist in lab coat recoiling from a specimen jar as a giant wasp beats against his laboratory window",
            setting_landscape="American small town, 1940s houses under attack from monstrous insect swarm filling the buzzing summer sky",
            dramatic_moment="wasp swarm descending on a power station as electricity crackles and the creatures grow larger in the arcs",
            symbolic_theme="nature perverted by science shown by a magnified wasp anatomy diagram alive and breaking through the glass",
            style_specific_prefix="1940s pulp horror insect illustration",
        )

    # ── David Copperfield ──────────────────────────────────────────────────
    if "david copperfield" in title_author:
        return BookMotif(
            iconic_scene="earnest young Victorian man at a writer's desk in London garret, candle and manuscripts before him, rising from poverty",
            character_portrait="sensitive young man in threadbare Victorian coat, honest eyes, quill in hand, determination in every line",
            setting_landscape="Victorian London progression from Dover cliffs to Whitechapel lanes, Yarmouth fishing boats, and Soho lodgings",
            dramatic_moment="young David arriving penniless at Aunt Betsey's gate as she strides out in fury then transforms with unexpected kindness",
            symbolic_theme="self-making shown by a quill pen transforming a broken childhood toy into a published book on a London desk",
            style_specific_prefix="Victorian bildungsroman narrative engraving",
        )

    # ── The Murder of Roger Ackroyd ───────────────────────────────────────
    if "roger ackroyd" in title_author or "murder of roger" in title_author:
        return BookMotif(
            iconic_scene="meticulous Belgian detective in a perfect English village garden gesturing toward a closed study door",
            character_portrait="egg-shaped detective with waxed moustache and immaculate suit examining a carved chair in a candlelit library",
            setting_landscape="King's Abbot English village, Tudor study with a locked door, herbaceous borders, and a moonlit terrace",
            dramatic_moment="assembled suspects in the drawing room as the detective's grey cells reveal the impossibly shocking solution",
            symbolic_theme="hidden guilt shown by a narrator's own pen lying beside a victim's chair and a closed locked door",
            style_specific_prefix="Golden Age detective illustration",
        )

    # ── Short Stories by Chekhov ────────────────────────────────────────────
    if "short stories" in title_author and "chekhov" in title_author:
        return BookMotif(
            iconic_scene="melancholy Russian characters at a samovar in a provincial sitting room, birch forest visible through the window",
            character_portrait="weary provincial Russian in a fur-collared coat, eyes distant above a steaming glass of tea",
            setting_landscape="birch-lined Russian countryside, a railway platform in grey mist, a cherry orchard in blossom",
            dramatic_moment="a gun mounted on a wall in Act One finally fired as ordinary life erupts into irreversible consequence",
            symbolic_theme="quiet desperation shown by a fading candle beside a samovar in a birch-frosted Russian window",
            style_specific_prefix="Russian literary realist watercolour sketch",
        )

    # ── Memoirs of Fanny Hill ──────────────────────────────────────────────
    if "fanny hill" in title_author:
        return BookMotif(
            iconic_scene="young country girl arriving in 18th-century London by coach, wide-eyed before St Paul's and the Georgian cityscape",
            character_portrait="rosy-cheeked Georgian young woman in modest travelling cloak, wide eyes absorbing the London street spectacle",
            setting_landscape="Georgian London streets, booksellers' windows, coffee houses, river barges, and Covent Garden colonnades",
            dramatic_moment="Fanny reuniting with her true love on a rain-glistened Georgian street as coach lamps illuminate their faces",
            symbolic_theme="innocence navigating Georgian society shown by a country violet pressed between the pages of a London ledger",
            style_specific_prefix="18th-century picaresque Georgian engraving",
        )

    # ── Justice (Galsworthy) ───────────────────────────────────────────────
    if "justice" in title_author and "galsworthy" in title_author:
        return BookMotif(
            iconic_scene="a young clerk in a solitary confinement cell pacing, grey walls closing in as the prison system grinds on",
            character_portrait="gentle young man in prison grey crouched at a cell door, defeated posture, knuckles white on iron bars",
            setting_landscape="Edwardian courthouse, barristers in wigs, the docks, and a grim prison interior with iron galleries",
            dramatic_moment="prisoner beating helplessly on a cell door in the dark as the warden's footsteps recede down the gallery",
            symbolic_theme="institutional injustice shown by balanced scales held by a blindfolded figure inside a prison door arch",
            style_specific_prefix="Edwardian social realist charcoal engraving",
        )

    # ── Noli Me Tangere ───────────────────────────────────────────────────
    if "noli me tangere" in title_author:
        return BookMotif(
            iconic_scene="young Filipino idealist confronting a Spanish friar in a colonial Manila drawing room lit by oil lamps",
            character_portrait="Crisostomo Ibarra in European suit, torn between love and revolution, Manila's colonial church behind him",
            setting_landscape="Spanish colonial Manila, capiz-shell windows, Calesa carriages, tropical plazas, and Laguna de Bay beyond",
            dramatic_moment="Ibarra's arrest at the pista ng bayan as colonial guards seize him amid lanterns and festival crowd",
            symbolic_theme="colonial awakening shown by a Philippine sampaguita blooming through cracked Spanish stone under dawn light",
            style_specific_prefix="late-19th-century Philippine nationalist realism",
        )

    # ── The Beautiful and Damned ───────────────────────────────────────────
    if "beautiful and damned" in title_author:
        return BookMotif(
            iconic_scene="golden couple in Jazz Age evening dress drifting through a glittering Manhattan rooftop party at midnight",
            character_portrait="beautiful dissipated young man in white tie, glazed eyes, champagne glass tilting, Manhattan skyline behind",
            setting_landscape="1920s Manhattan, Riverside Drive apartment, Long Island lawns, speakeasy booths, and a dawn Hudson River",
            dramatic_moment="once-glamorous couple in a bare apartment, beauty faded, fortune gone, staring past each other at winter light",
            symbolic_theme="gilded American decline shown by a champagne coupe cracked on a marble floor beside a wilting gardenia",
            style_specific_prefix="Jazz Age Art Deco illustration",
        )

    # ── Vanity Fair ─────────────────────────────────────────────────────
    if "vanity fair" in title_author:
        return BookMotif(
            iconic_scene="green-eyed social climber in Regency ball gown ascending a staircase of titled heads toward a coroneted door",
            character_portrait="Becky Sharp in emerald silk gown, calculating smile, opera glass raised in a Regency ballroom",
            setting_landscape="Regency-era London ballrooms, Brussels before Waterloo, a Brussels street under Napoleon's cannon thunder",
            dramatic_moment="Becky Sharp playing charades at Lord Steyne's house as Rawdon Crawley bursts through the door in fury",
            symbolic_theme="social ambition shown by a puppet stage where the puppet climbs over other puppets toward a gold crown",
            style_specific_prefix="Regency satirical novel illustration engraving",
        )

    # ── Second Variety ───────────────────────────────────────────────────
    if "second variety" in title_author:
        return BookMotif(
            iconic_scene="a soldier on a radioactive no-man's-land confronted by a small wounded boy who is actually a killer robot",
            character_portrait="battle-worn soldier in radiation suit aiming his rifle at a child-shaped robot on a blasted grey plain",
            setting_landscape="post-nuclear European wasteland, shattered buildings, grey ash sky, hidden robot claws in rubble",
            dramatic_moment="human survivors realising they cannot tell each other from killer machines as robots close in from all sides",
            symbolic_theme="dehumanised war shown by a child's shoe embedded in radioactive ash beside a mechanical claw",
            style_specific_prefix="Cold War science fiction graphite illustration",
        )

    # ── Works of Edgar Allan Poe ───────────────────────────────────────────
    if "edgar allan poe" in title_author or ("poe" in title_author and "edgar" in title_author):
        return BookMotif(
            iconic_scene="a black raven perched above a pallid scholar's chamber door as a pendulum swings and crimson masks fill the ballroom",
            character_portrait="tormented Gothic narrator in a candlelit study, raven above, the pit below, masque revellers beyond the door",
            setting_landscape="Gothic chamber with an iron pendulum, a crumbling house above a tarn, and a masquerade hall lit by coloured windows",
            dramatic_moment="the Red Death unmasked at the stroke of midnight as the entire masked ball freezes in horror",
            symbolic_theme="mortality and obsession shown by a raven silhouette over a cracked pendulum above an open grave",
            style_specific_prefix="Gothic Romantic horror chiaroscuro engraving",
        )

    # ── The Railway Children ──────────────────────────────────────────────
    if "railway children" in title_author:
        return BookMotif(
            iconic_scene="three children waving red petticoats frantically from a railway embankment to stop an oncoming steam train",
            character_portrait="eldest girl in Edwardian pinafore on the embankment, red flag aloft, steam locomotive thundering toward her",
            setting_landscape="Yorkshire valley railway line, green embankment, stone tunnel mouth, and smoke-puffed steam engines",
            dramatic_moment="father stepping out of the train's steam cloud to reunite with his children on the platform at last",
            symbolic_theme="faith and reunion shown by a child's paper train on rails leading back to a father's silhouette in steam",
            style_specific_prefix="Edwardian children's book illustration",
        )

    # ── Connecticut Yankee in King Arthur's Court ───────────────────────────
    if "connecticut yankee" in title_author or "king arthur s court" in title_author:
        return BookMotif(
            iconic_scene="19th-century American factory foreman in Camelot's tournament lists, wired electrical fence facing armoured knights",
            character_portrait="Hank Morgan in jeans and shirt beside a medieval knight, wrench in hand, gleam of Yankee ingenuity in his eye",
            setting_landscape="Arthurian Camelot castle contrasted with telegraph poles and a steam engine on a muddy medieval road",
            dramatic_moment="Hank's Gatling guns mowing down charging medieval knights at the final Battle of the Sand-Belt",
            symbolic_theme="industrial modernity against chivalric legend shown by a wrench laid across Excalibur on the round table",
            style_specific_prefix="Victorian satirical Arthurian illustration",
        )

    # ── The Turn of the Screw ────────────────────────────────────────────
    if "turn of the screw" in title_author:
        return BookMotif(
            iconic_scene="frightened governess on a tower staircase facing a translucent apparition while two pale children sleep below",
            character_portrait="Victorian governess, candle guttering, white-knuckled on a banister, eyes fixed on a ghost at the window",
            setting_landscape="Bly country house, misty lake, night-dark tower, overgrown gardens, and a pale ghost on the battlements",
            dramatic_moment="Miles collapsing in the governess's arms as the ghost of Peter Quint disappears into the darkened lawn",
            symbolic_theme="ambiguous evil shown by two halves of a face — one child's, one ghost's — in a black country-house mirror",
            style_specific_prefix="Victorian Gothic psychological illustration",
        )

    # ── Sorrows of Young Werther ─────────────────────────────────────────────
    if "werther" in title_author or "sorrows of young" in title_author:
        return BookMotif(
            iconic_scene="sensitive young man in blue coat and yellow waistcoat reading letters beneath a lime tree in a German summer meadow",
            character_portrait="Werther in his iconic blue coat, passionate eyes, clutching a love letter, stormy sky gathering behind",
            setting_landscape="Wetzlar countryside, Rhine valley village, chestnut trees, and Lotte's garden gate at golden hour",
            dramatic_moment="Werther's final night, blue coat draped over a chair, a pistol and an unfinished letter on the writing desk",
            symbolic_theme="Romantic anguish shown by a blue coat and yellow waistcoat crumpled beside an extinguished candle and letters",
            style_specific_prefix="German Romantic Sturm und Drang watercolour",
        )

    # ── Swann's Way ───────────────────────────────────────────────────────
    if "swann s way" in title_author or "swanns way" in title_author or "proust" in title_author:
        return BookMotif(
            iconic_scene="a narrator dunking a madeleine into a lime-blossom tea, Combray church spire materialising in golden memory",
            character_portrait="reflective Parisian narrator at a table, teacup raised, entire Combray childhood flooding into his mind's eye",
            setting_landscape="Combray village, hawthorn lanes, grandmother's garden, and gilded Parisian salon interiors merging in memory",
            dramatic_moment="Vinteuil's little phrase rising from the salon piano as Swann sees Odette's face in the music itself",
            symbolic_theme="involuntary memory shown by a madeleine crumb dissolving into a golden Combray church spire",
            style_specific_prefix="Belle Époque Impressionist literary illustration",
        )

    # ── Rip Van Winkle ───────────────────────────────────────────────────
    if "rip van winkle" in title_author:
        return BookMotif(
            iconic_scene="bearded old man in ragged 18th-century Dutch clothes waking from sleep among mist-shrouded Catskill boulders",
            character_portrait="ancient Rip Van Winkle in colonial hunting coat, white beard to his knees, bewildered in a changed village",
            setting_landscape="Catskill Mountains, Dutch colonial Hudson Valley, ghostly ninepins thunder in mist, and a village changed by decades",
            dramatic_moment="Rip entering his Sleepy Hollow village to find his wife dead, his house ruined, and his children grown strangers",
            symbolic_theme="time's passage shown by a colonial hat and musket overgrown with moss and mountain ferns",
            style_specific_prefix="American folklorish Hudson River School illustration",
        )

    # ── Plays (Susan Glaspell) ──────────────────────────────────────────────
    if "glaspell" in title_author or ("plays" in title and "glaspell" in title_author):
        return BookMotif(
            iconic_scene="two women in a farmhouse kitchen discovering a strangled canary in a box while men search uselessly elsewhere",
            character_portrait="quiet Midwestern farm woman in apron holding a small birdcage, eyes steady with female solidarity",
            setting_landscape="bleak Iowa farmhouse kitchen, cold stove, patchwork quilt half-finished, frosted window, empty bird cage",
            dramatic_moment="two women exchanging a silent look over the dead canary and its cage, sealing their silent sisterly verdict",
            symbolic_theme="silenced female voice shown by an empty birdcage and a knotted quilt on a bare farmhouse kitchen table",
            style_specific_prefix="early American Modernist theatre etching",
        )

    # ── Lysistrata ─────────────────────────────────────────────────────
    if "lysistrata" in title_author:
        return BookMotif(
            iconic_scene="Greek women barricading the Acropolis gates with olive branches while robed men plead in comic desperation below",
            character_portrait="Lysistrata in Athenian peplos, arms folded, standing before the Parthenon gates, expression imperious",
            setting_landscape="classical Athens Acropolis, Doric columns, olive-grove hillside, the Aegean glittering below in afternoon light",
            dramatic_moment="women declaring a love strike as armoured husbands crash to their knees before the Propylaea in comic agony",
            symbolic_theme="women's peace-power shown by a loom shuttle and distaff blocking a bronze Athenian spear below the Acropolis",
            style_specific_prefix="classical red-figure pottery comedy illustration",
        )

    # ── Anne of Avonlea ──────────────────────────────────────────────────
    if "anne of avonlea" in title_author:
        return BookMotif(
            iconic_scene="red-haired young teacher with a slate under her arm walking an apple-blossom lane to a one-room island school",
            character_portrait="Anne Shirley with braided auburn hair, bright grey eyes, walking between blooming apple trees toward a schoolhouse",
            setting_landscape="Prince Edward Island in spring, red soil lanes, apple orchards in full bloom, and a white clapboard schoolhouse",
            dramatic_moment="Anne presenting a wreath of apple blossoms at the school's first day as her students break into delighted laughter",
            symbolic_theme="imagination nurturing others shown by a red-haired figure planting words in children's minds like seeds in PEI soil",
            style_specific_prefix="Edwardian pastoral Canadian illustration",
        )

    # ── Pygmalion ──────────────────────────────────────────────────────
    if "pygmalion" in title_author and ("shaw" in title_author or "bernard" in title_author):
        return BookMotif(
            iconic_scene="phonetics professor pointing at notation on a blackboard while a Cockney flower girl practices vowels in a drawing room",
            character_portrait="Eliza Doolittle transformed in white tea-gown, enunciating carefully, Higgins tapping his phonograph behind her",
            setting_landscape="Edwardian Wimpole Street drawing room, phonograph cylinders, Covent Garden flowers sold from a basket nearby",
            dramatic_moment="Eliza's triumphant vowels at the ambassador's reception as Higgins and Pickering exchange stunned looks of pride",
            symbolic_theme="identity reshaped by language shown by a Cockney cap and violets beside a gold calling card and white gloves",
            style_specific_prefix="Edwardian social comedy illustration",
        )

    # ── Best American Humorous Short Stories ───────────────────────────────
    if "best american humorous" in title_author or ("humorous short stories" in title_author and "american" in title_author):
        return BookMotif(
            iconic_scene="a gallery of comic American characters from frontier tall-tales and parlour wit arrayed on a Mississippi steamboat deck",
            character_portrait="frontier yarn-spinner in coonskin cap and another in frock coat mid-jest, audience howling around them",
            setting_landscape="diverse American scenes stitched together — New England parlour, Mississippi levee, frontier saloon, and city street",
            dramatic_moment="tall tale reaching its impossible climax as the audience falls off their chairs in Yankee disbelief",
            symbolic_theme="American national humour shown by an ink quill tied to a lasso wrapped around a top hat and a frontier rifle",
            style_specific_prefix="19th-century American comic periodical illustration",
        )

    # ── The Happy Prince ──────────────────────────────────────────────────
    if "happy prince" in title_author:
        return BookMotif(
            iconic_scene="a golden statue stripped of sapphire eyes and ruby sword, a small swallow roosting on his bare shoulder in winter",
            character_portrait="the gilded Happy Prince, eyes weeping lead tears, a swallow delicately removing his last gold leaf",
            setting_landscape="a grey wintry city, gold-leaf spiraling off a statue onto a poor seamstress's garret, spire against leaden sky",
            dramatic_moment="the swallow dying at the statue's lead feet as the townspeople melt down the tarnished prince in the morning frost",
            symbolic_theme="charity unto death shown by a bare lead statue and a dead swallow on a snow-covered pedestal",
            style_specific_prefix="Victorian fairy tale watercolour illustration",
        )

    # ── Ivanhoe ──────────────────────────────────────────────────────
    if "ivanhoe" in title_author:
        return BookMotif(
            iconic_scene="armoured Saxon knight charging across a tournament field as Norman lances splinter and the crowd roars from lists",
            character_portrait="Ivanhoe in white and silver armour with disinherited knight's shield charging under a blazing summer sun",
            setting_landscape="Ashby-de-la-Zouche tournament ground, Sherwood Forest oaks, Torquilstone castle under siege in Norman England",
            dramatic_moment="Ivanhoe's siege of Torquilstone as Templars defend the battlements and Sherwood archers rain arrows from the woods",
            symbolic_theme="Saxon honour against Norman usurpation shown by a disinherited knight's shield against an ironclad Templar's cross",
            style_specific_prefix="Romantic medieval chivalric oil engraving",
        )

    # ── A Princess of Mars ───────────────────────────────────────────────
    if "princess of mars" in title_author or "barsoom" in title_author:
        return BookMotif(
            iconic_scene="Confederate cavalryman in Martian armour facing towering four-armed green warriors on a rust-red Barsoomian desert",
            character_portrait="John Carter in white cape and Barsoomian harness, sword raised, two moons in the violet Martian sky above",
            setting_landscape="red Martian desert, ruined ancient cities, pale Martian atmosphere, twin moons rising over ochre dunes",
            dramatic_moment="aerial battle of Martian flyers above the dying city as John Carter and Dejah Thoris embrace in the crow's nest",
            symbolic_theme="earthly courage transposed to alien heroism shown by a Confederate sword thrust into red Martian soil",
            style_specific_prefix="1910s planetary romance pulp illustration",
        )

    # ── The Awakening ────────────────────────────────────────────────────
    if "the awakening" in title_author and "chopin" in title_author:
        return BookMotif(
            iconic_scene="a Creole woman in white walking alone into warm Gulf of Mexico surf, small hotel behind her, free of society",
            character_portrait="Edna Pontellier in white muslin at the shore, face turned seaward, arms open, Gulf light on her hair",
            setting_landscape="Grand Isle Louisiana coast, Spanish moss, Creole cottages, a wide warm Gulf, and New Orleans French Quarter",
            dramatic_moment="Edna wading deeper into the Gulf as the final liberation from convention dissolves into green water",
            symbolic_theme="feminine self-possession shown by a woman's hat adrift on the Gulf alongside a torn calling card",
            style_specific_prefix="Southern Impressionist coastal watercolour",
        )

    # ── The Alchemist (Ben Jonson) ──────────────────────────────────────────
    if "the alchemist" in title_author and ("jonson" in title_author or "ben jon" in title_author):
        return BookMotif(
            iconic_scene="three Jacobean con artists in a London alchemist's den surrounded by retorts, bellows, and a queue of gulled clients",
            character_portrait="Face the con man in multiple disguises — puritan, scholar, captain — pocketing coin from a credulous merchant",
            setting_landscape="Jacobean London plague-emptied house, alchemy laboratory with furnaces, a street full of eager victims",
            dramatic_moment="the alchemist's furnace exploding as clients storm the house and the fraudsters scatter through back lanes",
            symbolic_theme="human greed alchemised from base credulity shown by a philosopher's stone made of painted lead",
            style_specific_prefix="Jacobean city comedy satirical engraving",
        )

    # ── Tristram Shandy ───────────────────────────────────────────────────
    if "tristram shandy" in title_author:
        return BookMotif(
            iconic_scene="a digressive narrator writing at a desk while his Uncle Toby builds fortifications on a billiard table behind him",
            character_portrait="Tristram Shandy's narrator mid-sentence at a writing desk, volume one open, ink blots, a marble table of fortifications",
            setting_landscape="18th-century English country house, a bowling green with toy fortifications, a library, and Toby's campaign maps",
            dramatic_moment="Uncle Toby and Corporal Trim's fort-building reaching theatrical heights as the family ignores Tristram's birth",
            symbolic_theme="narrative digression shown by a spiral doodle becoming a novel beside a blank marble page and a blotted quill",
            style_specific_prefix="18th-century comic meta-narrative engraving",
        )

    # ── Gargantua and Pantagruel ─────────────────────────────────────────────
    if "gargantua" in title_author or "pantagruel" in title_author or "rabelais" in title_author:
        return BookMotif(
            iconic_scene="an enormous laughing giant striding through a Renaissance French village, bells of Notre Dame caught in his hair",
            character_portrait="giant Gargantua in Renaissance doublet with a flagon the size of a hogshead, tearing a forest oak as a toothpick",
            setting_landscape="late-medieval France, Abbey of Thélème, giants feasting on entire oxen, and monks fleeing across monastery courtyards",
            dramatic_moment="Pantagruel opening his enormous mouth to shelter an army as rain falls on the giant tongue landscape inside",
            symbolic_theme="humanist excess and freedom shown by an overflowing banquet table scaled for titans with tiny men at the rim",
            style_specific_prefix="Renaissance Flemish comic giant illustration",
        )

    # ── Space Station 1 (Frank Belknap Long) ────────────────────────────────
    if "space station" in title_author and "long" in title_author:
        return BookMotif(
            iconic_scene="1950s astronauts in bubble-helmeted suits on a rotating orbital space station, Earth arc glowing below",
            character_portrait="retro-futuristic astronaut in chrome space suit tethering a module to a station as Earth fills the porthole",
            setting_landscape="1950s orbital space station with spoke-and-hub design, solar panels, and the blue curve of Earth below",
            dramatic_moment="emergency spacewalk on the station's hull as a meteor shower sparks off the metal skin against star-filled void",
            symbolic_theme="dawn of the space age shown by a human silhouette riveting a hull plate with Earth and Moon framed behind",
            style_specific_prefix="1950s retro space age pulp illustration",
        )

    # ── Arsène Lupin ───────────────────────────────────────────────────────
    if "ars ne lupin" in title_author or "arsene lupin" in title_author or "arsnne lupin" in title_author or ("lupin" in title_author and "leblanc" in title_author):
        return BookMotif(
            iconic_scene="elegant gentleman thief in a cape and top hat bowing to a duchess at a Belle Époque Paris soirée, jewels vanishing",
            character_portrait="Arsène Lupin in white gloves and top hat, moustached smile, a pilfered diamond barely visible in his cuff",
            setting_landscape="Belle Époque Paris, Second Empire mansions, Seine bridges, the Louvre gallery, and a rooftop at midnight",
            dramatic_moment="Lupin escaping across Paris rooftops at dawn, stolen painting under one arm, gendarmes closing from below",
            symbolic_theme="charming illegality shown by a bouquet of violets over a safe-cracking kit on a Haussmann velvet banquette",
            style_specific_prefix="Belle Époque Art Nouveau adventure illustration",
        )
```

---

## Placement Guide

Insert all new entries in `src/prompt_generator.py` **after** the last existing specific-book `if` block (currently the `around the world in eighty days` block ending around line 602) and **before** the author-fallback section beginning:

```python
    # Author/theme fallbacks.
    if "austen" in author:
```

The final file order inside `_motif_for_book()` will be:

1. Existing specific book entries (moby dick, alice, dracula, pride and prejudice, frankenstein, christmas carol, crime and punishment, romeo and juliet, journey to the centre, twenty thousand leagues, prince and the pauper, invisible man, time machine, jungle book, robinson crusoe, hamlet, oedipus, dorian gray, sherlock/sign of four, les miserables, call of the wild, we, around the world)
2. **NEW entries from this prompt (all books above)**
3. Author-fallback blocks (austen, dickens, mark twain, jules verne, dostoyevsky, shakespeare)
4. Generic fallback return

---

## Normalisation Notes

`_normalize()` lowercases the string and replaces all non-alphanumeric characters with spaces before collapsing multiple spaces. This means:

- `"A Room with a View"` → `"a room with a view"` → `"room with a view" in title_author` ✓
- `"Là-bas"` → `"l bas"` (the `à` becomes a space) → `"l bas" in title_author` ✓  
- `"Arsène Lupin"` → `"ars ne lupin"` (the `è` becomes a space) → `"ars ne lupin" in title_author` ✓
- `"Eve's Diary"` → `"eve s diary"` → `"eve s diary" in title_author` ✓
- `"A Doll's House"` → `"a doll s house"` → `"doll s house" in title_author` ✓
- `"2 B R 0 2 B"` → `"2 b r 0 2 b"` → `"2 b r 0 2 b" in title_author` ✓
- `"Swann's Way"` → `"swann s way"` → `"swann s way" in title_author` ✓
- `"Tristram Shandy"` → `"tristram shandy"` ✓

For the `emma` entry, the check uses `title.startswith("emma")` rather than `title_author` to avoid false matches with character names in other books.  For the `The Awakening` entry, the `chopin` author check prevents collision with any other story titled similarly.

---

## Testing

After inserting all entries, verify each book gets a unique motif:

```bash
# Test A Room with a View
python -c "
from src.prompt_generator import _motif_for_book
m = _motif_for_book({'title': 'A Room with a View', 'author': 'E. M. Forster'})
assert 'pivotal narrative' not in m.iconic_scene, 'GENERIC FALLBACK — entry missing!'
print('OK:', m.iconic_scene[:60])
"

# Test Gulliver's Travels
python -c "
from src.prompt_generator import _motif_for_book
m = _motif_for_book({'title': \"Gulliver's Travels\", 'author': 'Jonathan Swift'})
assert 'pivotal narrative' not in m.iconic_scene
print('OK:', m.iconic_scene[:60])
"

# Test Wind in the Willows
python -c "
from src.prompt_generator import _motif_for_book
m = _motif_for_book({'title': 'The Wind in the Willows', 'author': 'Kenneth Grahame'})
assert 'pivotal narrative' not in m.iconic_scene
print('OK:', m.iconic_scene[:60])
"

# Test Little Women
python -c "
from src.prompt_generator import _motif_for_book
m = _motif_for_book({'title': 'Little Women', 'author': 'Louisa May Alcott'})
assert 'pivotal narrative' not in m.iconic_scene
print('OK:', m.iconic_scene[:60])
"

# Batch test: iterate all 99 books and report any still hitting generic fallback
python -c "
import json, pathlib
from src.prompt_generator import _motif_for_book
catalog = json.loads(pathlib.Path('config/book_catalog.json').read_text())
generic_marker = 'pivotal narrative tableau'
failures = []
for book in catalog:
    m = _motif_for_book(book)
    if generic_marker in m.iconic_scene:
        failures.append(f\"{book['number']:>3}. {book['title']} — {book['author']}\")
if failures:
    print(f'FAIL: {len(failures)} books still use generic fallback:')
    for f in failures: print(' ', f)
else:
    print(f'PASS: All {len(catalog)} books have specific motifs.')
"
```

---

## MANDATORY: Verification

Before committing, confirm:

1. **No book returns the generic fallback** (the batch test above should print `PASS`).
2. **No motif field exceeds 24 words** (enforced by `_limit_words()` but best kept within spec at source).
3. **No two books share identical `iconic_scene` text** — each must be instantly recognisable as its own work.
4. **`style_specific_prefix` values are era-appropriate** for each book.
5. **Normalisation edge cases** (`Là-bas`, `Arsène Lupin`, `Swann's Way`, `Eve's Diary`, `A Doll's House`, `2 B R 0 2 B`) use the correct stripped forms in their match strings.

---

## Final Step

```bash
git add -A && git commit -m "PROMPT-09E: Book-specific motifs for all 99 books" && git push
```
