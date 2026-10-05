# Project Context

> 本文保留项目发起时的背景、架构构想与长期路线图；月份目标是初始规划，不表示
> 当前完成度或交付承诺。最新开发进度见 [reference.md 的当前阶段](reference.md#2-项目背景与当前阶段)，
> 项目约束见 [AGENTS.md](../AGENTS.md)。本页第 34 节为历史快照。

> 命名更新（2026-10-05）：项目伞形名称为 **Lifebase**（包名 `lifebase`、CLI 命令 `lifebase`）；四层 LifeSync / LifeVault / LifeGraph / HumanOS 名称不变；数据根目录为 `~/Lifebase/`。下文已同步更新系统级名称，其余「LifeSync」字样均指采集层（详见仓库 ADR-002）。

## 1. Project Overview

这是一个长期个人开源项目，目标是构建一套 **Personal Data Infrastructure / Digital Life Infrastructure**。

项目的核心目标不是做一个普通的 AI Chatbot，也不是单纯做聊天记录分析工具，而是：

> 将一个人分散在不同平台、设备、应用以及现实生活中的数字痕迹，长期、安全、可追溯地收集到由用户自己控制的数据基础设施中，并在此之上建立统一搜索、人生时间线、知识图谱、个人 AI、数字人格等能力。

核心思想：

> **Own your data first. Intelligence comes later.**

首先解决个人数据的获取、保存、标准化、关联和检索问题，然后再构建 AI 应用。

项目目前以 **个人开源项目** 为第一定位。

商业化不是当前主要目标。

# 2. Core Problem

现代人的个人数据被分散在大量彼此隔离的平台中，例如：

- 微信
- QQ
- SMS / iMessage
- Email
- ChatGPT
- Claude
- Gemini
- 抖音 / TikTok
- Instagram / 微博 / 小红书等社交平台
- Photos / Videos
- Apple Photos / Google Photos
- EXIF / GPS
- Google Maps / Apple Maps
- GPS location history
- 航班
- 火车
- 酒店
- 景点门票
- Trip.com / Booking 等旅行平台
- Calendar
- Uber / Grab / Taxi
- 银行流水
- Credit Card
- 支付宝
- 微信支付
- Amazon / 淘宝 / 京东
- 外卖
- Apple Health
- 运动 / 睡眠
- Git / GitHub
- 工作数据
- 学习数据
- Browser History
- Search History
- YouTube
- Spotify
- Netflix
- Steam
- Local Files
- Downloads
- Old hard drives
- App usage
- Screen time
- Shell history
- Home Assistant / IoT
- AI conversations
- Government / education / formal documents

这些数据实际上共同构成了一个人的：

- Activities
- Memories
- Relationships
- Locations
- Decisions
- Interests
- Preferences
- Knowledge
- Health
- Work
- Travel
- Purchases
- Life history

但目前这些数据被平台割裂。

项目希望建立属于用户自己的统一 Personal Data Layer。

# 3. Project Architecture

项目暂时分成四层：

```
                    HumanOS
         AI / Search / Timeline / Apps
                       ↑
                       │
                    LifeGraph
        Entities / Events / Relationships
          Evidence Fusion / Knowledge
                       ↑
                       │
                    LifeVault
       Raw Data / Normalized Data / Storage
                       ↑
                       │
                    LifeSync
        Collectors / Adapters / Importers
                       ↑
                       │
 ┌─────────────────────────────────────────────┐
 │ WeChat / Photos / GPS / Email / Browser     │
 │ ChatGPT / GitHub / Travel / Bank / Health   │
 │ Calendar / Files / Social / Devices / etc.  │
 └─────────────────────────────────────────────┘
```

四层职责严格分离。

# 4. LifeSync

LifeSync 是数据采集层。

负责：

- Collect
- Import
- Sync
- Detect
- Archive
- Incremental update

不同数据源不能假设使用相同采集方式。

Collector 分为几类。

## Passive Collector

长期自动采集：

```
GPS
Browser History
Git activity
ActivityWatch
Photos
Health
Filesystem metadata
```

## Connected Collector

通过 API / OAuth：

```
Gmail
Calendar
GitHub
Spotify
Strava
Notion
etc.
```

## Archive Collector

通过官方数据导出：

```
Google Takeout
ChatGPT Export
Claude Export
Apple Data Export
TikTok Export
etc.
```

用户只需要：

```
download export
       ↓
drop into Data Inbox
       ↓
Lifebase automatically detects source
       ↓
archive
       ↓
parse
```

## Local Database Collector

例如：

```
WeChat
QQ
Browser DB
local application databases
```

尽量读取用户自己设备上的数据，而不是依赖 Web scraping。

# 5. Collector Design Principle

不要试图开发：

> One universal scraper.

不同平台使用最适合它自己的方式。

优先级：

```
1. Official API / OAuth
2. Official Data Export
3. Local files / databases
4. Existing open-source extractor
5. User-triggered browser automation
6. Custom reverse engineering
```

尽量避免：

```
Keylogger
MITM
Permanent screen recording
Aggressive scraping
Account-risk automation
```

项目追求的是：

> **Reproducible collection, not perfect collection.**

# 6. Source Registry

系统需要维护：

```
Source Registry
```

例如：

```
Source      Domain        Method       Last Sync     Coverage

WeChat      Messages      Local DB     Today         96%
Photos      Media         Filesystem   Live          100%
GPS         Location      OwnTracks    Live          98%
Gmail       Email         API           Today         100%
ChatGPT     AI            Export        31 days ago   99%
GitHub      Coding        API/Git       Today         100%
Browser     Web           Local DB      Today         98%
QQ          Messages      Import        180 days      80%
Douyin      Social        Manual        Unknown       40%
```

Source Registry 需要记录：

```
source_id
source_type
collector_version
sync_method
last_sync
earliest_record
latest_record
coverage
status
errors
credentials_reference
parser_version
```

# 7. LifeVault

LifeVault 是长期数据存储层。

最重要原则：

> **Never destroy the original evidence.**

所有导入的数据首先进入 immutable RAW archive。

建议采用：

```
Bronze
↓
Silver
↓
Gold
```

# 8. Bronze Layer

Bronze 保存原始数据。

例如：

```
vault/

raw/
├── wechat/
├── qq/
├── chatgpt/
├── claude/
├── google/
├── photos/
├── gps/
├── browser/
├── github/
├── travel/
├── finance/
└── ...
```

可能包含：

```
ZIP
SQLite
JSON
HTML
CSV
XML
HEIC
JPEG
MOV
PDF
DB
binary files
```

Bronze 原则：

```
immutable
versioned
content hashed
never modified
re-parseable
```

未来 parser 或 AI 模型变得更好时，可以重新从 RAW 数据生成整个 Silver / Gold。

# 9. Silver Layer

Silver 是标准化后的事实数据。

例如：

```
entities.parquet
artifacts.parquet
events.parquet
observations.parquet
transactions.parquet
reservations.parquet
relationships.parquet
states.parquet
```

Silver 必须：

```
deterministic
reproducible
traceable
```

尽量不要让 LLM 决定 Silver 层事实。

# 10. Gold Layer

Gold 是推导数据。

例如：

```
Trips
Visits
Memories
Beliefs
Preferences
Relationships
Life periods
Topics
Summaries
Embeddings
Person profiles
AI interpretations
```

Gold 可以使用：

```
LLM
ML
heuristics
graph algorithms
evidence fusion
```

但 Gold 永远不能覆盖原始事实。

# 11. Life Primitives

不要围绕具体 App 建 schema。

例如不要设计：

```
WechatMessage
TripComBooking
GoogleMapLocation
```

而应该建立平台无关的 Life Primitives。

核心对象：

```
Entity
Artifact
Event
Observation
Transaction
Reservation
Relationship
State
Assertion
Evidence
```

## Entity

```
Person
Place
Company
Device
Account
Product
Organization
Project
```

## Artifact

```
Message
Email
Photo
Video
Document
File
Web page
Audio
```

## Event

```
Conversation
Meeting
Trip
Visit
Meal
Flight
Purchase
Activity
Work session
```

## Observation

```
GPS point
Heart rate
Sleep
Device usage
Temperature
Step count
Browser visit
```

## Transaction

```
Payment
Transfer
Refund
Subscription
Purchase
```

## Reservation

```
Flight
Train
Hotel
Restaurant
Event ticket
Attraction
```

## State

```
Job
School
Address
Relationship
Device ownership
Project membership
```

# 12. Provenance

这是项目最重要的设计原则之一。

任何数据都必须知道：

> Where did this come from?

例如：

```
source
source_record_id
raw_file
raw_offset
collector_version
parser_version
ingested_at
content_hash
```

任何 AI 推导出来的结论必须保留 evidence。

例如：

```
Claim:

"User visited Tokyo on 2027-04-05."

Evidence:

GPS point
Photo EXIF
Hotel reservation
Credit card transaction
Chat message
```

用户必须能够点击：

```
Why does LifeGraph believe this?
```

然后看到原始证据。

# 13. Evidence Fusion

现实中的一个事件通常会留下多个数字痕迹。

例如：

```
Flight reservation
+
GPS at airport
+
Photo in Tokyo
+
Hotel check-in
+
Credit card transaction
+
Chat messages
```

系统可以推导：

```
Tokyo Trip
2027-04-03 → 2027-04-09
confidence: 0.99
```

但必须区分：

```
Booked flight
```

和：

```
Actually took flight
```

Reservation 只能证明计划。

GPS / Photos / Transactions 等独立证据可以增强事件置信度。

# 14. Temporal Model

时间模型非常重要。

不能只有：

```
timestamp
```

至少应该考虑：

```
occurred_at
known_at
ingested_at
valid_from
valid_to
```

例如：

2026 年写了一篇文章回忆 2022 年发生的事情。

那么：

```
occurred_at = 2022
known_at = 2026
```

这对于 Past Me 极其重要。

# 15. Past Me

Past Me 是 HumanOS 上层应用之一。

例如：

```
Me @ 2019
Me @ 2022
Me @ 2024
```

核心原则：

> Past Me cannot know the future.

如果创建：

```
Past Me @ 2022-12-31
```

retrieval 必须限制：

```
known_at <= 2022-12-31
```

而不是简单：

```
occurred_at <= 2022-12-31
```

否则未来写下的历史回忆会泄露给 Past Me。

Past Me 可以使用：

```
Memories
Beliefs
Goals
Preferences
Relationships
Life state
Speaking style
Historical context
```

形成某个时间点的 Self Snapshot。

# 16. LifeGraph

LifeGraph 将事实关联起来。

例如：

```
Person
  ↓ knows
Person

Person
  ↓ visited
Place

Person
  ↓ worked_at
Company

Trip
  ↓ contains
Visit

Photo
  ↓ evidence_for
Visit

Transaction
  ↓ happened_at
Place
```

最终形成：

```
Personal Knowledge Graph
+
Temporal Graph
+
Evidence Graph
```

# 17. HumanOS

HumanOS 是最终交互层。

它不是数据源。

它建立在：

```
LifeSync
+
LifeVault
+
LifeGraph
```

之上。

潜在功能包括：

```
Personal Search
Life Timeline
People
Places
Trips
Memories
Ask My Life
Past Me
Council of Selves
Life Wrapped
Decision Journal
Prediction Tracker
Personality Evolution
What Changed Me?
Personal CRM
Family Knowledge Graph
AI Documentary
Personal Archive
```

# 18. Example Query

未来系统应该能够回答：

```
“我第一次去东京是什么时候？”
```

然后同时查询：

```
Flights
GPS
Photos
Hotels
Calendar
Transactions
Messages
Email
```

得到：

```
Tokyo Trip
2027-04-03 → 2027-04-09

Flights
SIN → HND
HND → SIN

Hotel
XXXX Hotel
6 nights

Places visited
23

Photos
437

People
A, B

Transactions
...

Evidence confidence
99%
```

并允许用户继续问：

```
“我那次旅行每天去了哪里？”

“同行的人是谁？”

“当时我在想什么？”

“那次旅行以后我的兴趣有什么变化？”
```

# 19. Existing Open-Source Technology

原则：

> Do not rebuild solved infrastructure.

需要优先研究和利用已有项目。

目前关注：

### HPI / Human Programming Interface

借鉴：

```
personal data adapters
unified Python interface
personal data source philosophy
```

非常接近 LifeSync 的思想。

### Promnesia

借鉴：

```
personal browsing memory
cross-source URL history
context reconstruction
```

### Dawarich

可用于：

```
location history
GPS timeline
trip detection
Google Timeline import
OwnTracks integration
```

### OwnTracks

可用于：

```
phone GPS capture
```

### Traccar

可用于：

```
GPS tracking backend
```

可能作为 sidecar，而不是自己重写 GPS server。

### ActivityWatch

可用于：

```
desktop activity
application usage
AFK
browser activity
```

### Immich

可用于：

```
photo/video management
metadata
EXIF
face recognition
location
```

不应该重新开发完整 photo management system。

### restic

用于：

```
encrypted backup
deduplication
remote backup
restore
```

不要自己发明 backup system。

### DuckDB + Parquet

MVP 数据分析层优先考虑：

```
Parquet
+
DuckDB
```

原因：

```
local-first
portable
cheap
excellent analytical querying
easy schema iteration
```

### PostgreSQL + pgvector

后期 HumanOS Web Application 可以加入：

```
PostgreSQL
pgvector
```

处理：

```
application state
transactions
relationships
vector retrieval
```

但 MVP 不应该过早依赖复杂数据库基础设施。

# 20. Initial Storage Strategy

MVP：

```
Local filesystem
+
content-addressed object storage
+
Parquet
+
DuckDB
+
SQLite
```

后期：

```
PostgreSQL
+
pgvector
```

必要时再考虑：

```
Neo4j
Milvus
Weaviate
Qdrant
```

不要因为“可能以后需要”而提前引入。

# 21. Media Storage

大型文件应该使用 content-addressed storage。

例如：

```
SHA256(photo)
→
objects/ab/cdef...
```

不同来源：

```
WeChat photo
QQ photo
Photo Library
Email attachment
```

如果内容相同：

```
4 references
↓
1 physical object
```

数据库只保存 hash reference。

# 22. Data Inbox

一个非常重要的 MVP 功能：

```
~/Lifebase/inbox/
```

用户把：

```
ChatGPT export.zip
Google Takeout.zip
WeChat export
Claude export
```

直接放进去。

系统：

```
watch inbox
      ↓
detect source
      ↓
select adapter
      ↓
hash
      ↓
archive RAW
      ↓
normalize
      ↓
update Source Registry
```

目标：

> Download → Drop → Done.

# 23. Collector Plugin Interface

LifeSync 必须从第一天设计成可扩展 adapter system。

概念接口：

```
Collector
├── detect()
├── validate()
├── ingest()
├── normalize()
├── checkpoint()
└── metadata()
```

Collector 输出统一 record。

Collector 不应该直接写 HumanOS database。

应该：

```
Collector
↓
RAW
↓
Normalizer
↓
Canonical records
```

# 24. Incremental Sync

Collector 必须考虑：

```
checkpoint
cursor
last_sync
hash
source_record_id
```

保证：

```
idempotent imports
```

同一个 export 导入 10 次不能产生 10 份数据。

# 25. Schema Evolution

Personal data system 生命周期可能是几十年。

因此 schema 一定会改变。

原则：

```
RAW never changes
Canonical schema is versioned
Parser is versioned
Derived data is disposable
```

例如：

```
schema_version = 3
parser_version = "wechat@0.4.1"
```

未来可以：

```
RAW
↓
parser v5
↓
rebuild Silver
↓
rebuild Gold
```

# 26. Privacy and Security

这是一个极高敏感度系统。

可能保存：

```
all chats
photos
location
financial transactions
health
relationships
emails
files
browser history
AI conversations
```

原则：

```
Local First
Privacy First
Encrypted at Rest
Minimal Cloud Exposure
User Controlled
```

禁止：

```
commit personal data to Git
commit API keys
public raw datasets
upload entire vault to LLM provider
```

如果调用远程 LLM：

```
retrieve minimal evidence
↓
redact when possible
↓
send only necessary context
```

长期考虑：

```
local embeddings
local models
encrypted backups
secret manager
```

# 27. Third-Party Privacy

聊天记录不只属于用户。

里面包含：

```
friends
family
coworkers
partners
clients
```

因此：

```
personal analysis ≠ permission to publish
```

项目默认：

```
local processing
private dataset
no public raw examples
```

Open-source demo 使用 synthetic dataset。

# 28. MVP Philosophy

不要第一版支持：

```
WeChat
QQ
Douyin
TikTok
Instagram
Bank
Health
Spotify
GPS
Photos
GitHub
...
```

这会导致 scope explosion。

MVP 的目标是证明完整 pipeline：

```
Source
↓
Collector
↓
RAW
↓
Normalize
↓
Query
↓
Evidence
```

而不是证明：

```
“支持 50 个平台。”
```

# 29. Suggested First Collectors

第一阶段考虑 3–5 个。

建议：

```
1. ChatGPT Export
2. Browser History
3. Git / GitHub
4. Photos + EXIF
5. Location / OwnTracks or Dawarich
```

也可以将 WeChat 作为 experimental collector。

原因：

这些来源分别覆盖：

```
conversation
web activity
work/coding
physical world
location
```

能够很好验证统一数据模型。

# 30. Development Roadmap

## Weekend Prototype

目标：

```
Data Inbox
RAW archive
one collector
Parquet
DuckDB
basic CLI query
```

证明：

```
export.zip
↓
Lifebase
↓
queryable data
```

## Month 1

实现：

```
Source Registry
Collector SDK
3 collectors
RAW Vault
Silver schema
hash deduplication
provenance
DuckDB query
```

## Month 3

实现：

```
5+ collectors
incremental sync
GPS
photos
browser
messages
basic entities
basic event reconstruction
search
```

## Month 6

实现：

```
LifeGraph
Evidence Fusion
Trips
People
Places
Timeline
full-text search
semantic search
```

## Month 12

开始：

```
HumanOS
Past Me
Ask My Life
Council of Selves
Life Wrapped
Decision Journal
```

# 31. Project Priority

当前优先级：

```
1. Data ownership
2. Data collection
3. Raw preservation
4. Normalization
5. Provenance
6. Search
7. LifeGraph
8. AI
9. Fancy UI
```

不要反过来。

尤其不要：

```
先做漂亮 AI chatbot
↓
再想数据从哪里来
```

正确顺序：

```
Data
↓
Infrastructure
↓
Knowledge
↓
Intelligence
↓
Experience
```

# 32. Project Success Criteria

项目早期成功不等于：

```
users
revenue
stars
```

第一阶段成功标准是：

> 我自己的数字生活开始稳定、持续地流入一个由我控制、可以重新解析、可以查询、可以验证的数据仓库。

具体：

```
multiple heterogeneous sources
↓
one ingestion system

multiple formats
↓
one canonical model

multiple evidence records
↓
one reconstructed event

AI answer
↓
clickable evidence
```

如果这一链路成立，项目核心价值就成立。

# 33. Long-Term Vision

最终系统可以理解：

```
Who am I?

Where have I been?

Who have I known?

What have I done?

What did I believe?

What did I want?

What did I buy?

What did I build?

What did I learn?

What changed me?

How did I become who I am today?
```

它不是：

```
AI clone
```

而更接近：

> **Version control + database + search engine + knowledge graph + AI interface for a human life.**

# 34. Initial Project Position（历史快照）

项目发起时处于：

```
Concept
↓
Architecture exploration
↓
Project initiation
```

当时尚未正式进入大规模 coding；该描述不代表当前开发状态。

当时最需要解决的是：

```
Collector architecture
Canonical schema
RAW Vault design
Source Registry
Provenance model
First MVP
Build vs Reuse decisions
```

而不是：

```
UI polish
monetization
large-scale cloud infrastructure
mobile app
social features
```

# 35. Guidance for Claude

When helping with this project:

1. Do not assume every component should be built from scratch.
2. Prefer mature open-source components where appropriate.
3. Preserve local-first and privacy-first principles.
4. Treat RAW data as immutable evidence.
5. Never treat LLM output as source truth.
6. Every derived assertion should ideally have provenance/evidence.
7. Avoid premature infrastructure complexity.
8. Keep the collector system modular.
9. Design for schema evolution and decades-long data lifetime.
10. Prioritize working vertical slices over platform coverage.
11. Distinguish facts, observations, plans and AI inferences.
12. Consider temporal semantics carefully.
13. Treat sensitive personal data and third-party data conservatively.
14. Prefer deterministic processing before LLM processing.
15. When proposing architecture, clearly distinguish:
    - Build
    - Reuse
    - Integrate
    - Defer
16. Challenge unnecessary complexity.
17. The immediate objective is a strong personal open-source project, not a VC startup.
18. Commercialization may be considered later but should not distort the current architecture.

When uncertain, optimize for:

> **Data ownership, longevity, reproducibility, inspectability and user control.**

# 36. One-Sentence Definition

> **Lifebase is a local-first personal data infrastructure that continuously collects, preserves and normalizes a person's fragmented digital life into an evidence-backed temporal LifeGraph, upon which HumanOS and personal AI applications can be built.**
