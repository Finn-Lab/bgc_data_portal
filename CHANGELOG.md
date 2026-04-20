# Changelog

## [3.1.0](https://github.com/EBI-Metagenomics/bgc_data_portal/compare/bgc_data_portal-v3.0.0...bgc_data_portal-v3.1.0) (2026-04-20)


### Features

* **discovery:** scope domain novelty to GCF bucket ([fc739a4](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/fc739a4abb94e1a60facad4a513b1cf6499cb364))
* **portal:** evaluate-asset region comparison, taxonomy hierarchy, UMAP fixes ([bed2939](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/bed2939565977c5da99e28aca8950a67468a783c))
* **portal:** filter asset-upload domains to PFAM/TIGRFAM + count skipped rows ([1f0e9a0](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/1f0e9a0ac767ce1682cb3bf8367f109db41d75dc))


### Bug Fixes

* **asset evaluation:** Fix file path extention pattern to align with ETL pipeline. `*tar.gz` and `*tgz` ([3fea228](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/3fea228cd84f624af5bb251e5759e7804264927c))
* **clustering:** convert HalfVector to list before numpy array construction ([8ad0dba](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/8ad0dbae55fc6a63a94d7796382ae0d203ba4250))
* **clustering:** read hdbscan version via importlib.metadata ([56818e5](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/56818e50226c24069fc1bfdeafda12e071138bcc))
* **clustering:** use HalfVector.to_list() for numpy conversion ([7cc35f4](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/7cc35f4cfb64e0951ef00e58550c03c8b404ba85))
* **Django ORM:** Manual migrations ([a1cf7ee](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/a1cf7ee7b84e72375296084cf6637b8905cd391a))
* **ingestion:** deduplicate cds_sequences batch by cds_id before bulk_create ([6591afb](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/6591afbf0c01bbf1734683f3f458845582fff4d6))
* **ingestion:** deduplicate domains batch by constraint key before bulk_create ([c5635f8](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/c5635f8e8adfacf19633137ee484338de8bc8f86))
* **portal:** align EMBEDDING_DIM with 960-dim DB column ([27a3fbd](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/27a3fbd79ebcb7b14d4cbb1ec6e0f697a4273e9f))
* **portal:** allow group-write on /app for ([998235a](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/998235ab53d6986ba1c3fed198261dcbb748f724))
* **portal:** bake ingress prefix into Vite base for prod build ([521b5db](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/521b5db6da2effcd65672b7e4a789328103deda1))
* **portal:** bump umap-learn to 0.5.12 for scikit-learn 1.6+ compat ([497bef4](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/497bef4e45e6c09d9f96c26db286ae088d36f36b))
* **portal:** match BGC embeddings case-insensitively in asset upload parser ([f3eba3f](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/f3eba3f43960608d3f2c869ec9e7b8e2fcc320bc))
* **portal:** run collectstatic on Django pod startup ([fbdbfa8](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/fbdbfa8a29ef9cd9d3220ae8e16f94a426f6a941))
* **portal:** show Protein Details card when clicking a CDS in Domain Architecture Comparison ([b91850e](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/b91850eec260091c68409da18a0e6c9b31a6e5d6))

## [3.0.0](https://github.com/EBI-Metagenomics/bgc_data_portal/compare/bgc_data_portal-v2.1.0...bgc_data_portal-v3.0.0) (2026-04-19)


### ⚠ BREAKING CHANGES

* **portal:** release new discovery platform

### Features

* **bgc-data-portal:** add self-contained k8s dev/prod infrastructure ([21e3af2](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/21e3af2b1edcfa2fddf98b7565fc9a4eb7e1deee))
* **ci:** support local-dev with KIND ([ab3b6c7](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/ab3b6c7cb230d2258d3e4c6ee083decc435d1649))
* **ci:** support version bump with please-release ([e87f65a](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/e87f65a09ab079d6646019145e9fc6d0d3559dcd))
* **dashboard:** Add aggregated region and ingestion patterns ([5f5de42](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/5f5de4215fa5b2c9888e33fe5e68bc9bcc979330))
* **dashboard:** Dorp chemical space map from explore/search modes ([d7074e9](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/d7074e90b748ceb6d4b3ef50bd9d6df70e1ea919))
* **dashboard:** element urls in db ([339029b](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/339029b18b4ab0678fa9864115b730d502d53c4f))
* **dashboard:** First draft of Asset evaluation ([c75cd90](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/c75cd90d7a86d5778fc1ea3563fc75ccc191d4bf))
* **dashboard:** Histograms in BGC Asset Evaluation ([8df3bee](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/8df3bee06840fe9f7aa80fa29e7ba7dfcad3829a))
* **dashboard:** Implemented core components of Asset evaluation ([65387d4](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/65387d4dfdd4fc01234c34b4847c12ef9d02f51f))
* **dashboard:** Support filtering by ChemOnt ([26305c5](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/26305c5b0c8339a560f7ad4857b2a667d08eb5b0))
* **dashboard:** Support full BGC and protein card in dashboard ([f0971e9](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/f0971e9d8c96360093a6e0192242d2db292cf0bf))
* **dashboard:** Support stats panel ([7e91ae6](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/7e91ae6040de9cabe3a359ce1db3ecc79a20aca9))
* **dashboard:** support validated bgcs beyond mibig ([a609e7b](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/a609e7b8d5f1fa2a38f7a057217fc7a06552ad66))
* **db:** Encode sequneces as blob ([fde4b41](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/fde4b41f2d648910aee9065eee614cfd5d0fd0b9))
* **db:** Support seed data generation for test and dev ([fb8f082](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/fb8f0825af813fa9875ddf0a38f29244206a78b4))
* **discovery platform:** suppor user submited assets ([79589f6](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/79589f6ca96a1c0a88bae53d40d885c4796124bb))
* **django:** Create a pattern—task,command,api ep, and front end—to expose basic stats ([ddeb0ac](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/ddeb0ace91b17f6cf6b6edbc48566837fafd8135))
* **django:** Support dashboard for exploration ([4110f9b](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/4110f9b854b207aca2fb745cf68e5511fd51d26d))
* **django:** Support dashboard frontend for exploration ([bf9188b](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/bf9188b250a689b435f72d2395c66c97bdae8cbb))
* **django:** Support domain and protein generation in seed data for discovery dashboard ([2866d5d](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/2866d5d0b92536a8ae3151b240c6b87bc84b02f7))
* **env:** Add activation script ([609e0f8](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/609e0f8ead499b9a8be8d9d6e9c68500a785ff77))
* **ingestion:** add bulk ingrstion patters for mgnify-bgcs-etl tables and parquets ([5659064](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/565906403446745a4de79fe5b5e0c9751f6eacdb))
* **landing page:** add cards to access dashboard modes ([fdbdcbc](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/fdbdcbcfc090f59314a01e069fd5e3e174a8ca5a))
* **lanfing page:** Support quickstart card ([3812618](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/3812618735e58a80827065c7e7c89b0cdada6672))
* **portal:** release new discovery platform ([63dadb9](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/63dadb9211bab247a045b1adb39ee9165023cc6b))
* **scoring infrastructure:** Include django commands for updates ([d73f717](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/d73f717eb8cf5ff1d7427cb8c59d4d07fc3ab734))


### Bug Fixes

* **BGC EMBEDDING:** Add migrations to allocate ESM_300M ([23bf19e](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/23bf19e04e0a2bc689ac65039a3d658160ab51cd))
* **ci:** typo in release.yml ([35487a5](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/35487a587448a88becfae41bcd1f403da2918831))
* **container:** fixes to build react ([cb625a9](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/cb625a9b4d1825ba2fe6a5998905d8b48ae1bbd3))
* **container:** Removed dirs from gitignore so react build doesnot fail ([250760e](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/250760e687ef96e15e6c91aea78036e27af833be))
* **dashboard:** BGC stats in Genome exploration beahaviour ([0a8d971](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/0a8d9716d3d6291fcc2a5f500bd00c787edd00fb))
* **dashboard:** BGC/genome roster behaviour on modes ([6d04996](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/6d04996f02ed7a7864d896db89cf9e46f433bcb4))
* **dashboard:** Card stripes and tabs fixed to match style ([1e9caf1](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/1e9caf1bbd217e0eb31535a299453b093dc395b6))
* **dashboard:** Chemical map not showing ([3f6d9e1](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/3f6d9e1f90a74384585468b668f1a60b67de6e3b))
* **dashboard:** Empty BGC map on emty genome shortlist ([c67ff51](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/c67ff51218199ea05bdbe8e7f47b72fce24107a7))
* **dashboard:** Fix Roster size ([b31f06e](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/b31f06e3d1d7014128ad7e6c9c88f24c9fec2e8c))
* **dashboard:** Plase api call for correct query similarity ([8d55c5f](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/8d55c5fe9d6d3c91b0219302ef63a3985f5e5ac0))
* **dashboard:** recover {BGC,Assembly} Detail cards ([b885a5c](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/b885a5c2ea0f040a4a0b6ff5949c155f060af24f))
* **dashboard:** recover BGC space map in Asset Evaluation ([259d4bb](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/259d4bb355e180e6f7c08b959a0563a80b611f37))
* **dashboard:** Resolve import to fix Assembly assestment ([8515cc0](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/8515cc0a378eed63425ed648658c546e2fc437e8))
* **dashboard:** Rosters fixed size ([003d8b4](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/003d8b46782f10b807a5a22e33972715c6965c93))
* **dashboard:** Scrolable BGC roster panel ([76a4ee8](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/76a4ee89f6f1911004a012e51b86c2f23a8d9780))
* **dashboard:** Shepher tour highliting the right elements ([5eaf51d](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/5eaf51da70b7f8f6868d3169d14beba89d29c450))
* **dashboard:** Sidebar overunning main content ([c27ce9d](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/c27ce9d6fef7b1061add050a1cdfd5faecac4e31))
* **dashboard:** similarity default columns ([f599df7](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/f599df7b6cd813e40e86072e7c20ca5080e388a0))
* **dashboard:** UX enhanced with biome lineage in sidebar ([12ad045](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/12ad045ba63644ad4e7a10ea3fd8e292f5e83991))
* **db models:** Ingestion pattern to include sequence records for 'discovery db' ([0324cbd](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/0324cbd0b2d2f4b8106fde6897973411e8fae8ee))
* **db models:** taxonomy to contigs; and add assembly types ([b900858](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/b90085886670dba06601c6b066f62dc47b3d1c09))
* **db/model:** improve unique constrains to biome and cds ([9efbf14](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/9efbf14ca0366af2faf008054eda32c60a4fd540))
* **DB:** add PGDATA to prevent break when redeploying ([69ed00f](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/69ed00feb458769f9b2313eb00a77927031cdc4e))
* **DB:** remove redundancy of ltree fields ([7127370](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/7127370ca519094de03d075049af8671ab572909))
* **deployments:** Unblock skaffold deploys on k8s clusters ([0a3ef2c](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/0a3ef2ce49f2ec1e813cdd04e05381e271a14e88))
* **dev site:** seed_discovery_data targets all models and fields ([1a05089](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/1a05089880173df9c46df6bf45885bcd02431180))
* **django:** Discovery dashboard correcly displayed ([5f2644c](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/5f2644cb7fd0bffe7cae8c6fb8a42d99538f1455))
* **EMBEDDINGS:** Manual DB migrations ([2130795](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/213079586c0d8d461a1ddb880b7ae5c2e31befaa))
* **ingestion pattern:** Include domain url handling ([8cef729](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/8cef7291bac95fcedd9d595fdb36ddcf0e8d9378))
* **ingestion pattern:** Include protein embedding loader ([b250e86](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/b250e860db76b803f59ce6595ab94a77eff8dcc6))
* **ingestion:** Ignore conflicts on duplicated unique constraints ([2a4f1bd](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/2a4f1bd4ccd32aca9e32460a2b88c13696f43edb))
* **keyword search:** Fix search pattern ([da25bb1](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/da25bb1eed2f210aae967093beef815cd8d42ff0))
* **loader:** Get_or_create instead of create on loaded regions ([5e88fd1](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/5e88fd17f7cfc16ac03dc0c42aef5fe9c9320f7e))
* **loader:** Ingnore conglicts on unique constraints ([32283d9](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/32283d937871a110c5a124f0cfa29ad89947ad6a))
* **loader:** Resolve domain aggregations ([948e334](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/948e334f8210d0e0040b861ce44c69d794bc8cd3))
* **LOADER:** Set max limit of csv filed to support sequnece loading ([69069e7](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/69069e72325bf42be8f198090636d33fe5e53f0d))
* **local deploy:** dont copy artifacts to local ([910900d](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/910900de3805568756c63bd9a2f4b467777be6a5))
* **quickstart slides:** correct blurring background ([d5e88eb](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/d5e88ebfcfa98519e37af0efe442a36ac6fdfa47))
* **scoring:** Amend data type for percentile calcs ([c6b03d6](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/c6b03d67754f69ec243843ac35ca152ad0726d58))
* **scoring:** Avoid collition of PFAM names ([adb911a](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/adb911a2b400b9b7086021716903fa592192013f))
* **search:** Fixed forms for keyword search ([f16afe0](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/f16afe023df67184cf6e1d41a0b4d3394b22da32))
* **seed_data:** Correct loading of discovery data to test accessioning pattern ([9222cb2](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/9222cb20f8615c9cb9a0481916e0c37c6e021c8c))


### Performance Improvements

* **bgc_aggregator:** Change esm model from 600M to 300M params ([448d36d](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/448d36defd11b09ab5efa55bf19dfcac04064cce))
* **django:** Redisign db models to scale with full data ([2e4e112](https://github.com/EBI-Metagenomics/bgc_data_portal/commit/2e4e112c0a72af1426f11574ef7ea543b0ca0673))
