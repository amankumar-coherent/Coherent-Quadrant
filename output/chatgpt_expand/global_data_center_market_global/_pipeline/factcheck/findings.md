# Chart fact-check (Google AI Mode) -- leads for analyst review

## NVIDIA Corporation
- scope: **core** -- The company develops and sells hardware and computing infrastructure, such as graphics processing units (GPUs) and AI platform solutions, directly for data center applications.
- status: active
- owner today: independent
- INCORRECT [AI & Sustainability Innovation]: NVIDIA introduced its DSX MaxLPS software as part of the DSX AI factory reference design to dynamically reallocate power between GPUs and racks in real time, enabling data center operators to run up to 40% more GPUs within the same power budget.
  - suggested: NVIDIA introduced its DSX MaxLPS software as part of the DSX platform to dynamically reallocate power between GPUs and racks in real time, enabling data center operators to run up to 40% more GPUs within the same power budget.
  - source: NVIDIA DSX MaxLPS official documentation and technical overview blogs detailing the suite's features and its connection with the broader DSX platform rather than a 'DSX AI factory reference design'.
- INCORRECT [Hyperscale & Cloud Customers]: NVIDIA announced that its Vera Rubin platform has entered full production with AI data center infrastructure racks running at cloud partners including Google Cloud, Microsoft Azure, and Oracle Cloud Infrastructure, as reported in the company's fiscal second-quarter 2027 financial results.
  - suggested: NVIDIA announced that its Vera Rubin platform is ramping into full production with racks running at partners including CoreWeave, Google Cloud, Microsoft Azure, Oracle Cloud Infrastructure and Nebius, as reported in the company's fiscal second-quarter 2027 financial results.
  - source: NVIDIA Second Quarter Fiscal 2027 Financial Results press release confirming that Vera Rubin is ramping into full production with specified cloud and neocloud infrastructure partners.
- INCORRECT [Hyperscale & Cloud Customers]: In its fiscal second-quarter 2027 earnings call, NVIDIA reported that its Data Center segment achieved a record $89 billion in revenue (representing 92.7% of total sales), with hyperscaler customer revenue specifically accounting for $49 billion of that total.
  - suggested: In its fiscal second-quarter 2027 earnings call, NVIDIA reported that its Data Center segment achieved a record $89 billion in revenue (representing 92.5% of total sales), with hyperscaler customer revenue specifically accounting for $49 billion of that total.
  - source: NVIDIA Fiscal Q2 2027 Earnings Call Transcript and slide metrics specifying $89 billion in Data Center revenue out of $96.22 billion total sales (equivalent to ~92.5%).

## Hewlett Packard Enterprise Company
- scope: **core** -- Hewlett Packard Enterprise Company itself designs, manufactures, and sells data center servers, storage systems, and networking hardware under its own name.
- status: active
- owner today: independent
- INCORRECT [Power & Cooling Efficiency]: The company's HPE Adaptive Rack Cooling System (ARCS) is a closed-loop liquid-to-air cooling solution that can achieve up to an 87.3% reduction in cooling-related power consumption and power usage effectiveness impact according to internal product evaluations published by Hewlett Packard Enterprise.
  - suggested: The company's direct liquid cooling design is a solution that can achieve up to an 87.3% reduction in cooling-related power consumption according to internal product evaluations published by Hewlett Packard Enterprise.
  - source: HPE Community Blog and Whitepaper analysis regarding Direct Liquid Cooling (https://community.hpe.com/t5/ai-unlocked/maximize-performance-sustainably-for-ai-training-with-hpe-cray/ba-p/7222696)
- INCORRECT [Rack & Enclosure Density]: According to an independent data center case study published by Eaton, Hewlett Packard Enterprise designed its scalable Modular Data Center (MDC) deployments using optimized infrastructure architectures capable of handling power densities up to 27kW or even 32kW per rack.
  - suggested: According to an independent data center case study published by Eaton, HP Enterprise designed its scalable Modular Data Center (MDC) deployments using optimized infrastructure architectures capable of handling power densities up to 27kW or even 32kW per rack.
  - source: Eaton Case Study (https://eaton.com.cn)
- INCORRECT [Hyperscale & Cloud Customers]: In fiscal year 2018, Hewlett Packard Enterprise officially ceased selling custom-designed commodity servers to Tier 1 service providers, which the company defined as Amazon, Google, Microsoft, Apple, Tencent, and Baidu, in order to pivot toward selling higher-margin products.
  - suggested: In fiscal year 2018, Hewlett Packard Enterprise officially ceased selling custom-designed commodity servers to Tier 1 service providers, which the company defined as Amazon, Google, Microsoft, Facebook, Apple, Tencent, Alibaba, and Baidu, in order to pivot toward selling higher-margin products.
  - source: CRN Report (https://www.crn.com/news/data-center/300094536/hpe-to-step-back-from-tier-1-service-provider-server-business-while-focusing-on-higher-margin-growth-areas)
- INCORRECT [Strategic Partnerships & Channels]: Hewlett Packard Enterprise honors global distributors and technology partners through its specialized channel programs, recognizing TD SYNNEX as its Global Distributor of the Year and Microsoft as its Global Technology Partner at the HPE Partner Growth Summit.
  - suggested: Hewlett Packard Enterprise honors global distributors and technology partners through its specialized channel programs, recognizing TD SYNNEX as its Global Distributor of the Year and Microsoft as its Global Technology Partner at the HPE Partner Growth Summit 2025.
  - source: https://hpe.com
- INCORRECT [R&D Investment & Financial Strength]: Hewlett Packard Enterprise reported research and development expenditures of $2.5 billion for the fiscal year ended October 31, 2025, which represents approximately 7% of its total net revenue of $34.3 billion, according to the company's annual report on Form 10-K.
  - suggested: Hewlett Packard Enterprise reported research and development expenditures of $2.5 billion for the fiscal year ended October 31, 2025, which represents approximately 7% of its total net revenue of $33.529 billion, according to the company's annual report on Form 10-K.
  - source: https://www.sec.gov/Archives/edgar/data/1645590/000164559025000130/hpe-20251031.htm

## Dell Technologies Inc.
- scope: **core** -- The company develops and sells its own enterprise data center hardware including servers, data storage solutions, and networking equipment under its Infrastructure Solutions Group.
- status: active
- owner today: independent
- INCORRECT [Rack & Enclosure Density]: The company reports that its Dell PowerRack Integrated Rack Scalable Systems support extreme-density workloads by managing up to 504 kW per ORv3 rack while utilizing a 4U Rack-mounted Coolant Distribution Unit that supplies up to 160 kW of cooling capacity, according to the Dell Integrated Rack Scalable Systems Page.
  - suggested: The company reports that its Dell PowerRack Integrated Rack Scalable Systems support extreme-density workloads by managing up to 504 kW per ORv3 rack while utilizing a 4U PowerCool Rack-mounted Coolant Distribution Unit that supplies up to 160 kW of cooling capacity, according to the Dell Integrated Rack Scalable Systems Page.
  - source: Dell Technologies Product Pages (https://www.dell.com/en-us/shop/storage-servers-and-networking-for-business/sf/integrated-rack-scalable-systems and https://infohub.delltechnologies.com/en-uk/p/dell-integrated-rack-scalable-systems-simplified-reliable-efficient-liquid-cooling-for-modern-data-centers/)
- INCORRECT [DCIM & Management Software]: Dell Technologies offers OpenManage Enterprise Power Manager, a specialized plug-in designed to monitor and control power consumption, track carbon emissions, and evaluate thermal health and resource utilization across up to 25,000 devices per console.
  - suggested: Dell Technologies offers OpenManage Enterprise, a specialized console designed to monitor and control power consumption, track carbon emissions, and evaluate thermal health and resource utilization across up to 25,000 devices per console (monitoring-only), while the earlier separate Power Manager plug-in functionality is now integrated natively into OME.
  - source: Dell Support Knowledge Base (https://www.dell.com/support/kbdoc/en-us/000175879/support-for-openmanage-enterprise)
- INCORRECT [AI & Sustainability Innovation]: The company announced its Concept Astro program in October 2025, which is an experimental platform utilizing agentic AI, digital twins, and real-time grid data to forecast data center power requirements and optimize workload scheduling based on green energy availability, according to a company disclosure.
  - suggested: The company announced its Concept Astro program in May 2025, which is an experimental platform utilizing agentic AI, digital twins, and real-time grid data to forecast data center power requirements and optimize workload scheduling based on green energy availability, according to a company disclosure.
  - source: Dell Technologies Corporate Blog (https://dell.com) and SiliconANGLE (https://siliconangle.com)
- INCORRECT [Global Revenue & Market Share]: The company reports a record full-year revenue of $60.8 billion for its Infrastructure Solutions Group in fiscal year 2026, representing a 40% year-over-year increase driven by $24.7 billion in AI server revenue.
  - suggested: The company reports a record full-year revenue of $60.8 billion for its Infrastructure Solutions Group in fiscal year 2026, representing a 40% year-over-year increase driven by $25 billion in AI server revenue.
  - source: Dell Technologies Fourth Quarter and Full-Year Fiscal 2026 Results
- INCORRECT [Strategic Partnerships & Channels]: Dell Technologies signed a Memorandum of Understanding with major IT distributor Tech Data in January 2025 to launch the Dell AI Factory channel initiative in India, establishing a Center of Excellence for pre-validated hardware-software data center solutions.
  - suggested: Dell Technologies signed a Memorandum of Understanding with major IT distributor Tech Data in November 2024 to launch the Dell AI Factory channel initiative in India, establishing a Center of Excellence for showcasing AI use cases and product demonstrations.
  - source: TD SYNNEX / Tech Data Press Release (January 2, 2025)
- INCORRECT [R&D Investment & Financial Strength]: In its annual report on Form 10-K for Fiscal 2026, the company reports a total research and development spending of $3.1 billion for both Fiscal 2026 and Fiscal 2025, representing approximately 2.7% of its record full-year Fiscal 2026 revenue of $113.5 billion.
  - suggested: In its annual report on Form 10-K for Fiscal 2026, the company reports a total research and development spending of $3,142 million for Fiscal 2026 and $3,061 million for Fiscal 2025, representing approximately 2.8% of its record full-year Fiscal 2026 revenue of $113.5 billion.
  - source: Dell Technologies Inc. Form 10-K for the Fiscal Year ended January 30, 2026

## Dell Inc.
- scope: **core** -- Dell Inc. manufactures and sells its own extensive lines of data center hardware, including PowerEdge servers and PowerVault/PowerStore storage systems, under its own brand name.
- status: active
- owner today: Dell Technologies Inc. 2016
- HQ: report says Round Rock, Texas, USA, AI Mode says Round Rock, United States
- INCORRECT [Compute & Storage Performance]: An independent comparative testing project conducted by Principled Technologies in May 2026 demonstrated that the Dell PowerStore 9500 storage array delivered superior IOPS, storage density, and latency performance compared to a rival all-NVMe enterprise array, according to the Principled Technologies study on CIO Influence.
  - suggested: An independent comparative testing project conducted by Principled Technologies in May 2026 demonstrated that the Dell PowerStore 9500 storage array delivered superior IOPS, storage density, and latency performance compared to a rival all-NVMe enterprise array, according to the Principled Technologies report.
  - source: https://principledtechnologies.com
- INCORRECT [AI & Sustainability Innovation]: Dell Technologies collaborated with the Scripps Institution of Oceanography on a pilot program using the Dell AI Factory with NVIDIA to process coral reef imagery, achieving a 20% reduction in costs and 32% lower carbon emissions by utilizing agentic AI to schedule processing during optimum energy windows.
  - suggested: Dell Technologies collaborated with the Scripps Institution of Oceanography on a pilot program using the Dell Concept Astro initiative to process coral reef imagery, achieving a 20% reduction in energy costs and 32% lower carbon emissions by utilizing AI to schedule processing during optimum energy windows.
  - source: Scripps Institution of Oceanography Press Release ("New Technology Infrastructure Streamlines AI-Powered Coral Research")
- INCORRECT [Installed Base & Deployments]: Hostinger completed the deployment of 800 Dell PowerEdge servers equipped with AMD EPYC processors to scale its global web hosting and server infrastructure.
  - suggested: Hostinger completed the deployment of 800 Dell PowerEdge R6615 servers equipped with AMD EPYC processors to scale its global web hosting and server infrastructure.
  - source: Hostinger Official Blog Release ("Hostinger's Record Investment: 800 Dell Servers With AMD EPYC Processors")
- INCORRECT [Strategic Partnerships & Channels]: Dell Technologies teamed up with Nvidia and Indian cloud provider NxtGen in January 2026 to build India's largest dedicated sovereign AI data center facility, deploying fully integrated liquid-cooled Dell IR5000 racks, PowerEdge XE9685L servers, and over 4,000 Nvidia Blackwell GPUs.
  - suggested: Dell Technologies teamed up with Nvidia and Indian cloud provider NxtGen in January 2026 to build India's largest dedicated sovereign AI factory, deploying fully integrated liquid-cooled Dell IR5000 racks, PowerEdge XE9685L servers, and over 4,000 Nvidia Blackwell GPUs.
  - source: Dell Technologies Official Press Release (January 2026) / Times of India

## Arista Networks, Inc.
- scope: **core** -- The company develops, makes, and sells data center switches, routers, and networking infrastructure software under its own name.
- status: active
- owner today: independent

## Wiwynn Corporation
- scope: **core** -- Wiwynn Corporation designs, manufactures, and sells data center compute, storage, and rack solutions under its own name.
- status: active
- owner today: Wistron Corporation 2012
- INCORRECT [Rack & Enclosure Density]: Wiwynn reports the development and debut of its double-wide Open Compute Project (OCP) compliant rack architecture at the OCP Global Summit, featuring integrated high-voltage DC (HVDC) power delivery supporting ±400/800 VDC and a liquid-cooled busbar designed for high-current loads.
  - suggested: Wiwynn reports the development and debut of its double-wide Open Compute Project (OCP) compliant rack architecture at the OCP Global Summit 2025, featuring integrated high-voltage DC (HVDC) power delivery supporting ±400/800 VDC and a liquid-cooled busbar designed for high-current loads.
  - source: Wiwynn Official Press Release October 2025 (https://www.wiwynn.com/news/wiwynn-debuts-double-wide-rack-architecture-for-next-generation-ai-at-ocp-global-summit-2025)
- INCORRECT [AI & Sustainability Innovation]: In April 2021, Microsoft partnered with Wiwynn in its Washington data center to test the deployment of energy-efficient two-phase immersion-cooled servers.
  - suggested: In April 2021, Microsoft partnered with Wiwynn in its Quincy data center to test the deployment of energy-efficient two-phase immersion-cooled servers.
  - source: Microsoft Official Innovation Blog / DatacenterDynamics report on Wiwynn and Microsoft
- INCORRECT [Installed Base & Deployments]: Wiwynn reported that it has shipped server racks to more than 350 data centers worldwide, as documented by DatacenterDynamics.
  - suggested: Wiwynn reported that it has shipped server racks to more than 350 data centers worldwide, as documented by W.Media.
  - source: https://w.media/wiwynn-unveils-server-rack-integration-plant-in-johor-malaysia-targets-hyperscale-data-centers/

## Amphenol Corporation
- scope: **core** -- The company designs, manufactures, and sells data center hardware infrastructure component products under its own name, including fiber optic transceivers, connectors, and cable assemblies for high-performance computing environments.
- status: active
- owner today: independent
- INCORRECT [Power & Cooling Efficiency]: The company reports that its nrgILS DC power panel platform, introduced in March 2026, optimizes data center energy management by integrating real-time current and voltage monitoring, load shedding of non-critical infrastructure, and sequenced recovery automation.
  - suggested: The company reports that its nrgILS DC power panel platform, introduced in January 2026, optimizes data center energy management by integrating real-time current and voltage monitoring, load shedding of non-critical infrastructure, and sequenced recovery automation.
  - source: Amphenol Network Solutions Press Release
- INCORRECT [R&D Investment & Financial Strength]: The company reported full year 2025 net sales of $23.1 billion, representing a 52% increase from 2024, alongside an adjusted operating margin of 26.2% and a net income of $5.4 billion, demonstrating robust overall financial health to sustain innovation as outlined in its 2025 Annual Report.
  - suggested: The company reported full year 2025 net sales of $23.1 billion, representing a 52% increase from 2024, alongside an adjusted operating margin of 26.2% and a net income of $4.3 billion, demonstrating robust overall financial health to sustain innovation as outlined in its 2025 Annual Report.
  - source: https://investors.amphenol.com/news-and-events/news-details/2026/Amphenol-Reports-Record-Fourth-Quarter-and-Full-Year-2025-Results/default.aspx

## Nutanix, Inc.
- scope: **core** -- The company develops and sells its own software-defined data center infrastructure and server virtualization platforms under the Nutanix name.
- status: active
- owner today: independent
- HQ: report says San Jose, California, USA, AI Mode says San Jose, United States

## Datapod Pty Ltd
- scope: **core** -- The company designs, engineers, and manufactures its own brand of physical modular data center infrastructure.
- status: active
- owner today: independent
- INCORRECT [DCIM & Management Software]: Datapod deploys its proprietary Integrated Monitoring and Control System (IMCS), a Modbus-based hardware and device management appliance built directly into its modular data center systems that offers local and remote access to performance data, as published on Datapod's corporate documentation.
  - suggested: Datapod deploys its proprietary Integrated Management and Control System (IMCS), a Modbus-based hardware and device management appliance built directly into its modular data center systems that offers local and remote access to performance data, as published on Datapod's corporate documentation.
  - source: Datapod Corporate Documentation via FAQ & Product Definition Pages (https://datapod.ai/10-frequently-asked-questions-about-datapods-modular-data-center/ and https://datapod.ai/what-do-you-get-when-you-order-a-datapod-modular-data-center/)
- INCORRECT [Hyperscale & Cloud Customers]: In April 2026, Datapod signed a six-year global supply agreement valued at up to $2.3 billion with hyperscaler Oracle to supply, deploy, and maintain modular AI data center infrastructure globally for Oracle Cloud Infrastructure.
  - suggested: In April 2026, Datapod signed a six-year global supply agreement valued at up to $1.65 billion with hyperscaler Oracle to supply, deploy, and maintain modular AI data center infrastructure globally for Oracle Cloud Infrastructure.
  - source: Australian Financial Review (https://www.afr.com/technology/oracle-signs-2-3b-deal-with-australian-data-centre-builder-datapod-20260421-p5zprv) and Investing.com (https://www.investing.com/news/company-news/why-is-oracle-stock-rallying-again-today-93CH-4665017)

## EnerSys
- scope: **core** -- The company develops, manufactures, and sells data center UPS energy storage systems and backup batteries under its own DataSafe brand.
- status: active
- owner today: independent
- HQ: report says Reading, Pennsylvania, USA, AI Mode says Reading, United States
- INCORRECT [Rack & Enclosure Density]: The DataSafe Noir lithium energy storage system supports up to 600 kW of output power per cabinet and up to 1.2 MW across two racks for high-density environments, as reported in the EnerSys DataSafe Noir Product Specifications.
  - suggested: The DataSafe Noir lithium energy storage system supports up to 600 kW of output power per cabinet and up to 1.2 MW across two cabinets for high-density environments, as reported in the EnerSys DataSafe Noir Product Specifications.
  - source: EnerSys DataSafe Noir Lithium Energy Storage System Overview
- INCORRECT [R&D Investment & Financial Strength]: EnerSys achieved a record full-year net sales figure of $3.75 billion for its fiscal year ended 31 March 2026, representing a 4% increase year-over-year, alongside an adjusted diluted EPS of $10.56, as reported in the company's official Q4 and full-year fiscal 2026 results press release.
  - suggested: EnerSys achieved a record full-year net sales figure of $3.8 billion for its fiscal year ended 31 March 2026, representing a 4% increase year-over-year, alongside an adjusted diluted EPS of $10.56, as reported in the company's official Q4 and full-year fiscal 2026 results press release.
  - source: https://investor.enersys.com/news/news-details/2026/EnerSys-Reports-Fourth-Quarter-and-Full-Year-Fiscal-2026-Results/default.aspx

## Asperitas BV
- scope: **core** -- The company itself develops and sells immersion liquid cooling systems under its own brand name specifically for data center facilities.
- status: active
- owner today: independent
- HQ: report says Haarlem, Netherlands, AI Mode says Amsterdam, Netherlands
- INCORRECT [Installed Base & Deployments]: Asperitas reports that its AIC24N immersion cooling solutions have been deployed across high-performance computing (HPC), enterprise, and GPU cluster case studies at the Shell Technology Centre, Bytesnet, Crédit Agricole, and the LOEWE Centre.
  - suggested: Asperitas reports that its immersion cooling solutions have been deployed across high-performance computing (HPC), enterprise, and GPU cluster case studies at the Shell Technology Centre, Bytesnet, Crédit Agricole, and the LOEWE Centre.
  - source: https://www.asperitas.com/partners
- INCORRECT [R&D Investment & Financial Strength]: A scale-up equity investment round successfully closed in September 2025, which included a €1.5 million investment from Invest-NL alongside capital from STECON GROUP, Shell Ventures, and PDENH to accelerate international expansion and portfolio innovation.
  - suggested: A scale-up equity investment round successfully closed in September 2025, which included an undisclosed investment from Invest-NL alongside capital from STECON GROUP, Shell Ventures, and PDENH to accelerate international expansion and portfolio innovation.
  - source: https://www.asperitas.com/news/asperitas-investment

## Cyber Power Systems, Inc.
- scope: **core** -- The company designs, manufactures, and sells data center infrastructure equipment such as datacenter UPS systems, power distribution units, and racks under its own CyberPower brand.
- status: active
- owner today: independent

## RPS S.p.A.
- scope: **core** -- The company itself manufactures and sells data center power hardware under its own name (Riello UPS).
- status: active
- owner today: Riello Elettronica Group

## Upsite Technologies, Inc. (subsidiary of Aquila, Inc.)
- scope: **core** -- The company itself designs, manufactures, and sells under its own name data center cooling infrastructure solutions such as airflow management, containment products, and rack power distribution units.
- status: active
- owner today: Aquila, Inc. 2018
- HQ: report says Albuquerque, New Mexico, USA, AI Mode says Albuquerque, United States
- INCORRECT [Global Revenue & Market Share]: Upsite Technologies, Inc. expanded its regional product availability to the Asian market by securing a distribution partnership with Data Clean Asia to deploy its physical physical infrastructure and cooling optimization systems.
  - suggested: Upsite Technologies, Inc. expanded its regional product availability to the Asian market by securing a distribution partnership with Data Clean Asia to deploy its physical infrastructure and cooling optimization systems.
  - source: https://upsite.com

## Salicru, S.A.
- scope: **core** -- The company manufactures and sells modular and high-power uninterruptible power supply (UPS) systems under its own brand name for data center infrastructure environments.
- status: active
- owner today: independent
- HQ: report says Sant Celoni, Spain, AI Mode says Palautordera, Spain
- INCORRECT [Hyperscale & Cloud Customers]: The company reports supplying six 500 kW SLC ADAPT2 modular uninterruptible power supply (UPS) systems to safeguard the Oxigen Data Center facility in Barcelona, Spain, which provides colocation and hybrid cloud services.
  - suggested: The company reports supplying six SLC ADAPT2 modular uninterruptible power supply (UPS) systems that allow configurations of up to 500 kW per cabinet to safeguard the Oxigen Data Center facility in Barcelona, Spain, which provides colocation and hybrid cloud services.
  - source: https://www.salicru.com/salicru-asegura-con-baterias-de-ion-de-litio-el-centro-de-dato.html

## Subzero Engineering (subsidiary of Senneca Holdings)
- scope: **core** -- The company itself manufactures and sells data center containment systems, aisle frames, and micro edge data center enclosures under its own name.
- status: active
- owner today: Senneca Holdings 2017
- HQ: report says Salt Lake City, Utah, USA, AI Mode says Salt Lake City, United States
- INCORRECT [Strategic Partnerships & Channels]: Subzero Engineering launched a strategic alliance with USG Mission Critical Solutions to deliver integrated, scalable, and sustainable containment infrastructure solutions tailored for high-density data center environments.
  - suggested: Subzero Engineering launched a strategic alliance with USG Mission Critical Solutions to deliver USG DataConstrux™ Containment powered by Subzero Engineering: modular aisle containment solutions designed for speed, performance and scalability.
  - source: https://www.usg.com/en-US/about-usg/news/usg-and-subzero-engineering-announce-strategic-alliance

## WEG S.A.
- scope: **core** -- WEG S.A. itself manufactures and sells power and infrastructure equipment for data centers under its own brand, including transformers, generators, and DCIM/BMS software systems.
- status: active
- owner today: independent
- INCORRECT [Power & Cooling Efficiency]: An integration of the W22 Premium Motor with the CFW701 HVAC variable speed drive in cooling tower infrastructure reduced electrical energy consumption by 48%, according to a WEG S.A. technical report.
  - suggested: An integration of the W22 Premium Motor with the CFW701 HVAC variable speed drive in cooling tower infrastructure reduced electrical energy consumption by up to 80%, according to a WEG S.A. technical report.
  - source: WEG Industrial Solutions - Cooling Tower Application Report (https://weg.net)
- INCORRECT [AI & Sustainability Innovation]: The company reports that its WEG Motion Fleet Management platform integrates the WEG Motor Specialist module, which uses machine learning and artificial intelligence algorithms to autonomously diagnose anomalies and run predictive maintenance for data center cooling systems.
  - suggested: The company reports that its WEG Motion Fleet Management platform integrates the WEG Motor Specialist module, which uses machine learning and artificial intelligence algorithms to autonomously diagnose anomalies and run predictive maintenance for electric motors.
  - source: WEG Institutional News - WEG Motor Specialist Launch (https://weg.net)

## EAE Elektrik A.Ş.
- scope: **core** -- The company manufactures and sells data center power distribution systems (busbars) and rack cabinets under its own name.
- status: active
- owner today: independent
- INCORRECT [Installed Base & Deployments]: The company's E-Line KX Aluminium 4000 A low-voltage busbar system was selected as the designated transformer busbar component integrated within Eaton's NordicEPOD 2.0 MW modular data center platform architecture, as verified in Eaton's technical product specifications.
  - suggested: The company's E-Line KX Aluminium 5000 A low-voltage busbar system was selected as the designated transformer busbar component integrated within Eaton's NordicEPOD 2.0 MW modular data center platform architecture, as verified in Eaton's technical product specifications.
  - source: Eaton Modular Data Center G A Critical Power Skid Technical Specifications

## OptiCool Technologies LLC (subsidiary of Calvary Robotics)
- scope: **core** -- The company designs, manufactures, and sells its own brand of two-phase liquid cooling infrastructure solutions for data center environments.
- status: active
- owner today: Invio Automation 2026
- HQ: report says Webster, New York, USA, AI Mode says Webster, United States
- INCORRECT [Power & Cooling Efficiency]: An engineering laboratory evaluation completed in March 2026 for a major aerospace company simulated an 80 kW rack heat load and verified that OptiCool Technologies' 120 kW rear-door heat exchanger effectively sustained a 70°F exit temperature while drawing a steady-state power load of only 550 W.
  - suggested: An engineering laboratory evaluation completed in March 2026 for a major aerospace company simulated an 80 kW rack heat load and verified that OptiCool Technologies' 120 kW rear-door heat exchanger effectively sustained a 70°F exit temperature while drawing a steady-state power load of only 550 W under a system ambient temperature set point of 75°F.
  - source: https://opticooltechnologies.com/case-study/breaking-the-100-kw-barrier/
- INCORRECT [R&D Investment & Financial Strength]: OptiCool Technologies is an affiliate or operating subsidiary of Calvary Automation, which acquired the company in July 2012.
  - suggested: OptiCool Technologies is an affiliate or operating subsidiary of Calvary Automation, which co-founded the company in July 2012.
  - source: Rochester Business Journal (July 2012 report on OptiCool's founding)

## Tate Access Floors, Inc. (subsidiary of Kingspan Group PLC)
- scope: **core** -- The company develops and sells its own data center cooling infrastructure, containment systems, structural ceilings, and raised access floors under its own brand name.
- status: active
- owner today: Kingspan Group PLC 2000
- HQ: report says Jessup, Maryland, USA, AI Mode says Columbia, USA
- INCORRECT [Power & Cooling Efficiency]: A study published by the company details that server airflow leakage occurs at rates between 23% and 135% of their designed flow rate, and demonstrates that its pressure-sensing automatic airflow dampering platform reduces annualized PUE, according to Cabling Installation & Maintenance.
  - suggested: A study published by the company details that server airflow leakage occurs at rates between 23% and 135% of their designed flow rate, according to Cabling Installation & Maintenance.
  - source: Cabling Installation & Maintenance White Paper Coverage (://cablinginstall.com)
- INCORRECT [Rack & Enclosure Density]: The company reports in its product documentation that its PowerAire fan assist modules provide targeted, variable-speed airflow capable of cooling up to 25 kW of IT load per rack panel combination to solve localized high-density hot spots.
  - suggested: The company reports in its product documentation that its PowerAire fan assist modules provide targeted, variable-speed airflow capable of cooling up to 16 kW of IT load per rack panel combination to solve localized high-density hot spots.
  - source: Tate Flooring Product Brochure (tateglobal.com/media/e3npfdoy/tate-flooring-product-brochure-rs-en-us.pdf)
- INCORRECT [DCIM & Management Software]: The company reports that its raised-floor fan tiles feature local control options, allowing them to be client-controlled or managed automatically using one to three rack-mounted temperature sensors.
  - suggested: The company reports that its SmartAire electronically controlled variable air volume dampers feature local control options, allowing them to be client-controlled or managed automatically using one to three rack-mounted temperature sensors.
  - source: Tate In-Floor Cooling Solutions Product Data Sheet (://hatchell.com)
- INCORRECT [Installed Base & Deployments]: The company reports deployments of its RMG600 raised access flooring systems at the Meta data center facility in Dublin.
  - suggested: The company reports deployments of its RMG raised access flooring systems at the Meta data center facility in Dublin.
  - source: Tate Global case study: 'Meta Dublin | New build office access flooring project'
