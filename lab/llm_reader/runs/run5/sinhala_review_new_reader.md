# Sinhala check: the new reader (/ActualText) vs today's extractor (pypdf)

The new reader takes the text the PDF itself stores for each Sinhala cluster (`/ActualText`), instead of the drawn glyphs. No model is involved.
Every line holding Sinhala is listed, for both PDFs. Please compare the **new reader** column with the PDF as you see it and mark the last column.

`what changed` compares the letters after Unicode decomposition (NFD): *reordered only* = the same letters, put in the right order; *letters restored* = letters today's extractor lost.

## Api_Denna_Script.pdf

Lines: today 301, new reader 301. Lines with Sinhala: 59 (0 unchanged, 33 reordered only, 26 with letters restored). Words with a vowel sign before its letter: today 101, new reader 0.

| line | today (pypdf) | **new reader** | what changed | correct? |
|---|---|---|---|---|
| 1 | Api ෙදන්නා | Api දෙන්නා | reordered only | |
| 25 | Kasun: " දවසක මෙම ෙරස්ටුරන්ට් එකක් පටන් ගන්නවා ." | Kasun: "දවසක මගේම රෙස්ටුරන්ට් එකක් පටන් ගන්නවා." | letters restored: +ග් | |
| 48 | Kasun: " මිස් ! මිස් ! ඔයාෙ ෙෆන් එක !" | Kasun: "මිස්! මිස්! ඔයාගේ ෆෝන් එක!" | letters restored: +ග්්ා | |
| 55 | Anudi: " අෙන් , Thank you! මම දැක්ෙකවත් නෑ ." | Anudi: "අනේ, Thank you! මම දැක්කෙවත් නෑ." | reordered only | |
| 56 | Kasun: " වැස්ස නිසා ෙවන්න ඇති ." | Kasun: "වැස්ස නිසා වෙන්න ඇති." | reordered only | |
| 58 | Anudi: " ෙම් ඔයාෙ බිස්නස් එකද ?" | Anudi: "මේ ඔයාගේ බිස්නස් එකද?" | letters restored: +ග් | |
| 59 | Kasun: " ඔව් . ෙපාඩියට පටන් ගත්ෙත් ." | Kasun: "ඔව්. පොඩියට පටන් ගත්තේ." | reordered only | |
| 60 | Anudi: " තනියමද ෙම් හැමෙම කරන්ෙන් ?" | Anudi: "තනියමද මේ හැමදේම කරන්නේ?" | letters restored: +ද් | |
| 61 | Kasun: " ඔව් . රැපියල් පන්දහසකින් පටන් ගත්ෙත් . තව ඉස්සරහට යන්න තමයි | Kasun: "ඔව්. රුපියල් පන්දහසකින් පටන් ගත්තේ. තව ඉස්සරහට යන්න තමයි | letters restored: +ු / -ැ | |
| 62 | බලාෙපාෙරාත්තුව ." | බලාපොරොත්තුව." | reordered only | |
| 66 | Anudi: " ෙහෙල තාත්ෙත් ." | Anudi: "හෙලෝ තාත්තේ." | letters restored: +්ා | |
| 67 | Father (over the phone): " අනුදි , ඔයා ෙකාෙහද ඉන්ෙන් ? ඉක්මනට ෙගදර එන්න . අපිට | Father (over the phone): "අනුදි, ඔයා කොහෙද ඉන්නේ? ඉක්මනට ගෙදර එන්න. අපිට | reordered only | |
| 68 | ඔයාෙ කසාෙද ගැන කතා කරන්න තිෙයනවා ." | ඔයාගේ කසාදෙ ගැන කතා කරන්න තියෙනවා." | letters restored: +ග් | |
| 70 | Anudi: " හරි තාත්ෙත් . මම එන්නම් ." | Anudi: "හරි තාත්තේ. මම එන්නම්." | reordered only | |
| 74 | Anudi: " එෙහනම් මම යන්නම් . ආෙයත් හම්බෙවමු ." | Anudi: "එහෙනම් මම යන්නම්. ආයෙත් හම්බවෙමු." | reordered only | |
| 75 | Kasun: " හරි . පරිස්සමින් යන්න ." | Kasun: "හරි. පරිස්සමින් යන්න." | reordered only | |
| 89 | Anudi: " අදත් ෙත් එකක් ගන්න පුළුවන්ද ?" | Anudi: "අදත් තේ එකක් ගන්න පුළුවන්ද?" | reordered only | |
| 91 | Kasun: " අද නම් ෙත් එක විතරක් ෙනෙවයි . Short eats තිෙයනවා ." | Kasun: "අද නම් තේ එක විතරක් නෙවෙයි. Short eats තියෙනවා." | reordered only | |
| 121 | Father: " අද මම ඔයාව දැක්කා අර ෙකාල්ලා එක්ක ." | Father: "අද මම ඔයාව දැක්කා අර කොල්ලා එක්ක." | reordered only | |
| 123 | Anudi: " කවුද තාත්ෙත් ?" | Anudi: "කවුද තාත්තේ?" | reordered only | |
| 124 | Father: " අර පාෙර් කෑම විකුණන ෙකාල්ලා . ඒ ළමයා කවුද ?" | Father: "අර පාරේ කෑම විකුණන කොල්ලා. ඒ ළමයා කවුද?" | reordered only | |
| 126 | Anudi: " තාත්ෙත් , එයා කසුන් . මෙ යාළුෙවක් ." | Anudi: "තාත්තේ, එයා කසුන්. මගේ යාළුවෙක්." | letters restored: +ග් | |
| 127 | Father: " යාළුෙවක් විතරද ? ඒ ළමයට ෙමානවද තිෙයන්ෙන් ? තමන්ෙ කියලා හරියට | Father: "යාළුවෙක් විතරද? ඒ ළමයට මොනවද තියෙන්නේ? තමන්ගේ කියලා හරියට | letters restored: +ග් | |
| 128 | තැනක්වත් නෑ ." | තැනක්වත් නෑ." | reordered only | |
| 130 | Anudi: " එයාට හීනයක් තිෙයනවා තාත්ෙත් ." | Anudi: "එයාට හීනයක් තියෙනවා තාත්තේ." | reordered only | |
| 132 | Father: " හීනවලින් පවුල් ජීවත් කරන්න බෑ අනුදි . සල්ලි ඕෙන් . අනාගතයක් තිෙයන්න | Father: "හීනවලින් පවුල් ජීවත් කරන්න බෑ අනුදි. සල්ලි ඕනේ. අනාගතයක් තියෙන්න | reordered only | |
| 133 | ඕෙන් ." | ඕනේ." | reordered only | |
| 149 | Anudi: " ඇයි ඔයා ෙම් තරම් මහන්සි ෙවන්ෙන් ?" | Anudi: "ඇයි ඔයා මේ තරම් මහන්සි වෙන්නේ?" | reordered only | |
| 151 | Kasun: " මට ඔයාෙ පවුෙලන් කවදාවත් ඔයාට මම ගැළෙපන්ෙන් නෑ කියලා අහන්න ඕෙන් | Kasun: "මට ඔයාගේ පවුලෙන් කවදාවත් ඔයාට මම ගැළපෙන්නේ නෑ කියලා අහන්න ඕනේ | letters restored: +ග් | |
| 152 | නෑ ." | නෑ." | reordered only | |
| 154 | Anudi: " මට ඔයාෙ සල්ලි ඕෙන් නෑ කසුන් . මට ඔයාවයි ඕෙන් ." | Anudi: "මට ඔයාගේ සල්ලි ඕනේ නෑ කසුන්. මට ඔයාවයි ඕනේ." | letters restored: +ග් | |
| 156 | Kasun: " ඒත් මට ඕෙන් ඔයාට ෙහාඳ අනාගතයක් ෙදන්න ." | Kasun: "ඒත් මට ඕනේ ඔයාට හොඳ අනාගතයක් දෙන්න." | reordered only | |
| 159 | Kasun: " ෙහෙල , කසුන් කතා කරන්ෙන් ." | Kasun: "හෙලෝ, කසුන් කතා කරන්නේ." | letters restored: +්ා | |
| 161 | Representative (over the phone): " ඔයාලෙ food products අෙ branches කිහිපයකට | Representative (over the phone): "ඔයාලගේ food products අපේ branches කිහිපයකට | letters restored: +ගප්් | |
| 162 | supply කරන්න අපි කැමතියි . ඒ ගැන කතා කරන්න පුළුවන්ද ?" | supply කරන්න අපි කැමතියි. ඒ ගැන කතා කරන්න පුළුවන්ද?" | reordered only | |
| 164 | Kasun: " ඇත්තටම සර් ? ඒක ෙලාකු අවස්ථාවක් ." | Kasun: "ඇත්තටම සර්? ඒක ලොකු අවස්ථාවක්." | reordered only | |
| 167 | Anudi: " ෙමාකද වුෙ ?" | Anudi: "මොකද වුණේ?" | letters restored: +ණ් | |
| 169 | Kasun: " අනුදි ... අපිට ෙලාකු order එකක් ලැෙබන්න යන්ෙන් ." | Kasun: "අනුදි... අපිට ලොකු order එකක් ලැබෙන්න යන්නේ." | reordered only | |
| 205 | Anudi: " ෙකාෙහාමද කසුන් ? වැෙ හරියනවද ?" | Anudi: "කොහොමද කසුන්? වැඩේ හරියනවද?" | letters restored: +ඩ් | |
| 206 | Kasun: " තාම හරියට විසඳුමක් නෑ අනුදි . බැංකුෙවන්වත් investor ෙකෙනක්ෙගන්වත් | Kasun: "තාම හරියට විසඳුමක් නෑ අනුදි. බැංකුවෙන්වත් investor කෙනෙක්ගෙන්වත් | reordered only | |
| 207 | උදව්වක් ලැබුෙ නෑ ." | උදව්වක් ලැබුණේ නෑ." | letters restored: +ණ් | |
| 209 | Anudi: " හැමෙම හරියයි කසුන් . ඔයා උත්සාහය අතාරින්න එපා ." | Anudi: "හැමදේම හරියයි කසුන්. ඔයා උත්සාහය අතාරින්න එපා." | letters restored: +ද් | |
| 211 | Kasun: " මම උත්සාහ කරනවා අනුදි ." | Kasun: "මම උත්සාහ කරනවා අනුදි." | reordered only | |
| 221 | Kasun: " ආයුෙබවන් සර් . වාඩිෙවන්න ." | Kasun: "ආයුබෝවන් සර්. වාඩිවෙන්න." | letters restored: +්ා | |
| 227 | Father: " ෙම්ෙක් රැපියල් මිලියන ෙදකක් තිෙයනවා ." | Father: "මේකේ රුපියල් මිලියන දෙකක් තියෙනවා." | letters restored: +ු / -ැ | |
| 230 | Kasun: " ෙබාෙහාම ස්තූතියි සර් . ෙම්ක මට ෙලාකු උදව්වක් ." | Kasun: "බොහොම ස්තූතියි සර්. මේක මට ලොකු උදව්වක්." | reordered only | |
| 232 | Father: " හැබැයි එක ෙකාන්ෙසියක් තිෙයනවා ." | Father: "හැබැයි එක කොන්දේසියක් තියෙනවා." | letters restored: +ද් | |
| 234 | Father: " ඔයා මෙ දුවෙගන් ඈත් ෙවන්න ඕෙන් ." | Father: "ඔයා මගේ දුවගෙන් ඈත් වෙන්න ඕනේ." | letters restored: +ග් | |
| 246 | Kasun: " සර් ... මට ඕෙන් අනුදිව මිසක් ඔයාෙ සල්ලි ෙනෙවයි ." | Kasun: "සර්... මට ඕනේ අනුදිව මිසක් ඔයාගේ සල්ලි නෙවෙයි." | letters restored: +ග් | |
| 249 | Kasun: " මෙ වාපාරය මමම ෙගාඩනගා ගන්නම් . ඒත් මෙ ආදෙර් සල්ලිවලට අතාරින්න | Kasun: "මගේ ව්‍යාපාරය මමම ගොඩනගා ගන්නම්. ඒත් මගේ ආදරේ සල්ලිවලට අතාරින්න | letters restored: +ගගය්්් | |
| 250 | මට බෑ ." | මට බෑ." | reordered only | |
| 252 | Kasun: " මට සමාෙවන්න සර් ." | Kasun: "මට සමාවෙන්න සර්." | reordered only | |
| 270 | Anudi: " ඔයාෙ හීෙන් ඇත්තටම හැබෑ වුණා කසුන් ." | Anudi: "ඔයාගේ හීනේ ඇත්තටම හැබෑ වුණා කසුන්." | letters restored: +ග් | |
| 272 | Kasun: " ඔයා මාව විශ්වාස කළ නිසා ." | Kasun: "ඔයා මාව විශ්වාස කළ නිසා." | reordered only | |
| 277 | Father: " මට සමාෙවන්න පුතා . මම එදා වැරදියට හිතුෙව් ." | Father: "මට සමාවෙන්න පුතා. මම එදා වැරදියට හිතුවේ." | reordered only | |
| 279 | Father: " ඔයාට සාර්ථක ෙවන්න මෙ සල්ලි ඕෙන් වුෙ නෑ . ඔයාට ඕෙන් වුෙ ඔයා ගැන | Father: "ඔයාට සාර්ථක වෙන්න මගේ සල්ලි ඕනේ වුණේ නෑ. ඔයාට ඕනේ වුණේ ඔයා ගැන | letters restored: +ගණණ්්් | |
| 280 | විශ්වාස කරන ෙකෙනක් විතරයි ." | විශ්වාස කරන කෙනෙක් විතරයි." | reordered only | |
| 287 | " සමහර ආදර කතාවලට සල්ලි ඕෙන් නෑ . තමන්ෙ හීන විශ්වාස කරන ෙකෙනක් හිටියම | "සමහර ආදර කතාවලට සල්ලි ඕනේ නෑ. තමන්ගේ හීන විශ්වාස කරන කෙනෙක් හිටියම | letters restored: +ග් | |
| 288 | ඇති ." | ඇති." | reordered only | |

## Api_Denna_Script_v2.pdf

Lines: today 301, new reader 301. Lines with Sinhala: 59 (0 unchanged, 33 reordered only, 26 with letters restored). Words with a vowel sign before its letter: today 101, new reader 0.

| line | today (pypdf) | **new reader** | what changed | correct? |
|---|---|---|---|---|
| 1 | Api ෙදන්නා | Api දෙන්නා | reordered only | |
| 25 | Kasun: " දවසක මෙම ෙරස්ටුරන්ට් එකක් පටන් ගන්නවා ." | Kasun: "දවසක මගේම රෙස්ටුරන්ට් එකක් පටන් ගන්නවා." | letters restored: +ග් | |
| 48 | Kasun: " මිස් ! මිස් ! ඔයාෙ ෙෆන් එක !" | Kasun: "මිස්! මිස්! ඔයාගේ ෆෝන් එක!" | letters restored: +ග්්ා | |
| 55 | Anudi: " අෙන් , Thank you! මම දැක්ෙකවත් නෑ ." | Anudi: "අනේ, Thank you! මම දැක්කෙවත් නෑ." | reordered only | |
| 56 | Kasun: " වැස්ස නිසා ෙවන්න ඇති ." | Kasun: "වැස්ස නිසා වෙන්න ඇති." | reordered only | |
| 58 | Anudi: " ෙම් ඔයාෙ බිස්නස් එකද ?" | Anudi: "මේ ඔයාගේ බිස්නස් එකද?" | letters restored: +ග් | |
| 59 | Kasun: " ඔව් . ෙපාඩියට පටන් ගත්ෙත් ." | Kasun: "ඔව්. පොඩියට පටන් ගත්තේ." | reordered only | |
| 60 | Anudi: " තනියමද ෙම් හැමෙම කරන්ෙන් ?" | Anudi: "තනියමද මේ හැමදේම කරන්නේ?" | letters restored: +ද් | |
| 61 | Kasun: " ඔව් . රැපියල් පන්දහසකින් පටන් ගත්ෙත් . තව ඉස්සරහට යන්න තමයි | Kasun: "ඔව්. රුපියල් පන්දහසකින් පටන් ගත්තේ. තව ඉස්සරහට යන්න තමයි | letters restored: +ු / -ැ | |
| 62 | බලාෙපාෙරාත්තුව ." | බලාපොරොත්තුව." | reordered only | |
| 66 | Anudi: " ෙහෙල තාත්ෙත් ." | Anudi: "හෙලෝ තාත්තේ." | letters restored: +්ා | |
| 67 | Father (over the phone): " අනුදි , ඔයා ෙකාෙහද ඉන්ෙන් ? ඉක්මනට ෙගදර එන්න . අපිට | Father (over the phone): "අනුදි, ඔයා කොහෙද ඉන්නේ? ඉක්මනට ගෙදර එන්න. අපිට | reordered only | |
| 68 | ඔයාෙ කසාෙද ගැන කතා කරන්න තිෙයනවා ." | ඔයාගේ කසාදෙ ගැන කතා කරන්න තියෙනවා." | letters restored: +ග් | |
| 70 | Anudi: " හරි තාත්ෙත් . මම එන්නම් ." | Anudi: "හරි තාත්තේ. මම එන්නම්." | reordered only | |
| 74 | Anudi: " එෙහනම් මම යන්නම් . ආෙයත් හම්බෙවමු ." | Anudi: "එහෙනම් මම යන්නම්. ආයෙත් හම්බවෙමු." | reordered only | |
| 75 | Kasun: " හරි . පරිස්සමින් යන්න ." | Kasun: "හරි. පරිස්සමින් යන්න." | reordered only | |
| 89 | Anudi: " අදත් ෙත් එකක් ගන්න පුළුවන්ද ?" | Anudi: "අදත් තේ එකක් ගන්න පුළුවන්ද?" | reordered only | |
| 91 | Kasun: " අද නම් ෙත් එක විතරක් ෙනෙවයි . Short eats තිෙයනවා ." | Kasun: "අද නම් තේ එක විතරක් නෙවෙයි. Short eats තියෙනවා." | reordered only | |
| 121 | Father: " අද මම ඔයාව දැක්කා අර ෙකාල්ලා එක්ක ." | Father: "අද මම ඔයාව දැක්කා අර කොල්ලා එක්ක." | reordered only | |
| 123 | Anudi: " කවුද තාත්ෙත් ?" | Anudi: "කවුද තාත්තේ?" | reordered only | |
| 124 | Father: " අර පාෙර් කෑම විකුණන ෙකාල්ලා . ඒ ළමයා කවුද ?" | Father: "අර පාරේ කෑම විකුණන කොල්ලා. ඒ ළමයා කවුද?" | reordered only | |
| 126 | Anudi: " තාත්ෙත් , එයා කසුන් . මෙ යාළුෙවක් ." | Anudi: "තාත්තේ, එයා කසුන්. මගේ යාළුවෙක්." | letters restored: +ග් | |
| 127 | Father: " යාළුෙවක් විතරද ? ඒ ළමයට ෙමානවද තිෙයන්ෙන් ? තමන්ෙ කියලා හරියට | Father: "යාළුවෙක් විතරද? ඒ ළමයට මොනවද තියෙන්නේ? තමන්ගේ කියලා හරියට | letters restored: +ග් | |
| 128 | තැනක්වත් නෑ ." | තැනක්වත් නෑ." | reordered only | |
| 130 | Anudi: " එයාට හීනයක් තිෙයනවා තාත්ෙත් ." | Anudi: "එයාට හීනයක් තියෙනවා තාත්තේ." | reordered only | |
| 132 | Father: " හීනවලින් පවුල් ජීවත් කරන්න බෑ අනුදි . සල්ලි ඕෙන් . අනාගතයක් තිෙයන්න | Father: "හීනවලින් පවුල් ජීවත් කරන්න බෑ අනුදි. සල්ලි ඕනේ. අනාගතයක් තියෙන්න | reordered only | |
| 133 | ඕෙන් ." | ඕනේ." | reordered only | |
| 149 | Anudi: " ඇයි ඔයා ෙම් තරම් මහන්සි ෙවන්ෙන් ?" | Anudi: "ඇයි ඔයා මේ තරම් මහන්සි වෙන්නේ?" | reordered only | |
| 151 | Kasun: " මට ඔයාෙ පවුෙලන් කවදාවත් ඔයාට මම ගැළෙපන්ෙන් නෑ කියලා අහන්න ඕෙන් | Kasun: "මට ඔයාගේ පවුලෙන් කවදාවත් ඔයාට මම ගැළපෙන්නේ නෑ කියලා අහන්න ඕනේ | letters restored: +ග් | |
| 152 | නෑ ." | නෑ." | reordered only | |
| 154 | Anudi: " මට ඔයාෙ සල්ලි ඕෙන් නෑ කසුන් . මට ඔයාවයි ඕෙන් ." | Anudi: "මට ඔයාගේ සල්ලි ඕනේ නෑ කසුන්. මට ඔයාවයි ඕනේ." | letters restored: +ග් | |
| 156 | Kasun: " ඒත් මට ඕෙන් ඔයාට ෙහාඳ අනාගතයක් ෙදන්න ." | Kasun: "ඒත් මට ඕනේ ඔයාට හොඳ අනාගතයක් දෙන්න." | reordered only | |
| 159 | Kasun: " ෙහෙල , කසුන් කතා කරන්ෙන් ." | Kasun: "හෙලෝ, කසුන් කතා කරන්නේ." | letters restored: +්ා | |
| 161 | Representative (over the phone): " ඔයාලෙ food products අෙ branches කිහිපයකට | Representative (over the phone): "ඔයාලගේ food products අපේ branches කිහිපයකට | letters restored: +ගප්් | |
| 162 | supply කරන්න අපි කැමතියි . ඒ ගැන කතා කරන්න පුළුවන්ද ?" | supply කරන්න අපි කැමතියි. ඒ ගැන කතා කරන්න පුළුවන්ද?" | reordered only | |
| 164 | Kasun: " ඇත්තටම සර් ? ඒක ෙලාකු අවස්ථාවක් ." | Kasun: "ඇත්තටම සර්? ඒක ලොකු අවස්ථාවක්." | reordered only | |
| 167 | Anudi: " ෙමාකද වුෙ ?" | Anudi: "මොකද වුණේ?" | letters restored: +ණ් | |
| 169 | Kasun: " අනුදි ... අපිට ෙලාකු order එකක් ලැෙබන්න යන්ෙන් ." | Kasun: "අනුදි... අපිට ලොකු order එකක් ලැබෙන්න යන්නේ." | reordered only | |
| 205 | Anudi: " ෙකාෙහාමද කසුන් ? වැෙ හරියනවද ?" | Anudi: "කොහොමද කසුන්? වැඩේ හරියනවද?" | letters restored: +ඩ් | |
| 206 | Kasun: " තාම හරියට විසඳුමක් නෑ අනුදි . බැංකුෙවන්වත් investor ෙකෙනක්ෙගන්වත් | Kasun: "තාම හරියට විසඳුමක් නෑ අනුදි. බැංකුවෙන්වත් investor කෙනෙක්ගෙන්වත් | reordered only | |
| 207 | උදව්වක් ලැබුෙ නෑ ." | උදව්වක් ලැබුණේ නෑ." | letters restored: +ණ් | |
| 209 | Anudi: " හැමෙම හරියයි කසුන් . ඔයා උත්සාහය අතාරින්න එපා ." | Anudi: "හැමදේම හරියයි කසුන්. ඔයා උත්සාහය අතාරින්න එපා." | letters restored: +ද් | |
| 211 | Kasun: " මම උත්සාහ කරනවා අනුදි ." | Kasun: "මම උත්සාහ කරනවා අනුදි." | reordered only | |
| 221 | Kasun: " ආයුෙබවන් සර් . වාඩිෙවන්න ." | Kasun: "ආයුබෝවන් සර්. වාඩිවෙන්න." | letters restored: +්ා | |
| 227 | Father: " ෙම්ෙක් රැපියල් මිලියන ෙදකක් තිෙයනවා ." | Father: "මේකේ රුපියල් මිලියන දෙකක් තියෙනවා." | letters restored: +ු / -ැ | |
| 230 | Kasun: " ෙබාෙහාම ස්තූතියි සර් . ෙම්ක මට ෙලාකු උදව්වක් ." | Kasun: "බොහොම ස්තූතියි සර්. මේක මට ලොකු උදව්වක්." | reordered only | |
| 232 | Father: " හැබැයි එක ෙකාන්ෙසියක් තිෙයනවා ." | Father: "හැබැයි එක කොන්දේසියක් තියෙනවා." | letters restored: +ද් | |
| 234 | Father: " ඔයා මෙ දුවෙගන් ඈත් ෙවන්න ඕෙන් ." | Father: "ඔයා මගේ දුවගෙන් ඈත් වෙන්න ඕනේ." | letters restored: +ග් | |
| 246 | Kasun: " සර් ... මට ඕෙන් අනුදිව මිසක් ඔයාෙ සල්ලි ෙනෙවයි ." | Kasun: "සර්... මට ඕනේ අනුදිව මිසක් ඔයාගේ සල්ලි නෙවෙයි." | letters restored: +ග් | |
| 249 | Kasun: " මෙ වාපාරය මමම ෙගාඩනගා ගන්නම් . ඒත් මෙ ආදෙර් සල්ලිවලට අතාරින්න | Kasun: "මගේ ව්‍යාපාරය මමම ගොඩනගා ගන්නම්. ඒත් මගේ ආදරේ සල්ලිවලට අතාරින්න | letters restored: +ගගය්්් | |
| 250 | මට බෑ ." | මට බෑ." | reordered only | |
| 252 | Kasun: " මට සමාෙවන්න සර් ." | Kasun: "මට සමාවෙන්න සර්." | reordered only | |
| 270 | Anudi: " ඔයාෙ හීෙන් ඇත්තටම හැබෑ වුණා කසුන් ." | Anudi: "ඔයාගේ හීනේ ඇත්තටම හැබෑ වුණා කසුන්." | letters restored: +ග් | |
| 272 | Kasun: " ඔයා මාව විශ්වාස කළ නිසා ." | Kasun: "ඔයා මාව විශ්වාස කළ නිසා." | reordered only | |
| 277 | Father: " මට සමාෙවන්න පුතා . මම එදා වැරදියට හිතුෙව් ." | Father: "මට සමාවෙන්න පුතා. මම එදා වැරදියට හිතුවේ." | reordered only | |
| 279 | Father: " ඔයාට සාර්ථක ෙවන්න මෙ සල්ලි ඕෙන් වුෙ නෑ . ඔයාට ඕෙන් වුෙ ඔයා ගැන | Father: "ඔයාට සාර්ථක වෙන්න මගේ සල්ලි ඕනේ වුණේ නෑ. ඔයාට ඕනේ වුණේ ඔයා ගැන | letters restored: +ගණණ්්් | |
| 280 | විශ්වාස කරන ෙකෙනක් විතරයි ." | විශ්වාස කරන කෙනෙක් විතරයි." | reordered only | |
| 287 | " සමහර ආදර කතාවලට සල්ලි ඕෙන් නෑ . තමන්ෙ හීන විශ්වාස කරන ෙකෙනක් හිටියම | "සමහර ආදර කතාවලට සල්ලි ඕනේ නෑ. තමන්ගේ හීන විශ්වාස කරන කෙනෙක් හිටියම | letters restored: +ග් | |
| 288 | ඇති ." | ඇති." | reordered only | |
