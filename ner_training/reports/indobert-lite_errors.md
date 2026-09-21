# Error analysis — `indobert-lite` on gold test set

Format: **gold** vs **pred** (tag inline). Hanya kalimat yang mengandung kesalahan.

Total kalimat dengan kesalahan: **3 / 135**

### [hard_names] #1
- gold: `Pagi min, <PERSON>Fajar</PERSON> di sini, sinyal hilang sejak fajar tadi.`
- pred: `Pagi min, Fajar di sini, sinyal hilang sejak fajar tadi.`
- missed (FN): `Fajar` (PERSON)

### [hard_address] #2
- gold: `Kirim ke kantor desa, <ADDRESS>Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan</ADDRESS>.`
- pred: `Kirim ke kantor <ADDRESS>desa, Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan</ADDRESS>.`
- missed (FN): `Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan` (ADDRESS)
- spurious/boundary (FP): `desa, Desa Tanjung Sari RT 002 RW 001, Kab. Lampung Selatan` (ADDRESS)

### [mixed_pii] #3
- gold: `email saya andi.wijaya at gmail dot com ya kak`
- pred: `email saya <PERSON>andi.wijaya</PERSON> at gmail dot com ya kak`
- spurious/boundary (FP): `andi.wijaya` (PERSON)
