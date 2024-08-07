from .schemas import BgcSearchInputSchema,BgcSearchOutputSchema
from typing import List, Set, Dict

class BgcAggregator:
    @staticmethod
    def single(input_schemas: List[BgcSearchInputSchema], detector_names: List[str]) -> List[BgcSearchOutputSchema]:
        return [
            BgcSearchOutputSchema(
                bgc_ids=[bgc.bgc_id],
                bgc_accessions=[bgc.bgc_accession],
                assembly_accession=bgc.assembly_accession,
                contig_mgyc=bgc.contig_mgyc,
                start_position=bgc.start_position,
                end_position=bgc.end_position,
                bgc_detector_names=[bgc.bgc_detector_name],
                bgc_class_names=[bgc.bgc_class_name]
            )
            for bgc in input_schemas
        ]

    @staticmethod
    def union(input_schemas: List[BgcSearchInputSchema], detector_names: List[str]) -> List[BgcSearchOutputSchema]:
        grouped_by_contig: Dict[str, List[BgcSearchInputSchema]] = {}
        
        # Step 1: Group by contig_mgyc
        for schema in input_schemas:
            if schema.contig_mgyc not in grouped_by_contig:
                grouped_by_contig[schema.contig_mgyc] = []
            grouped_by_contig[schema.contig_mgyc].append(schema)

        output_schemas = []

        # Step 2: Process each group for overlapping regions
        for contig_mgyc, schemas in grouped_by_contig.items():
            

            # Sort schemas by start_position to make it easier to detect overlaps
            schemas.sort(key=lambda s: s.start_position)

            if len(schemas)<2:
                continue

            current_group = schemas[0]
            aggregated_ids = {current_group.bgc_id}
            aggregated_accessions = {current_group.bgc_accession}
            aggregated_detector_names = {current_group.bgc_detector_name}
            aggregated_class_names = {current_group.bgc_class_name}

            for i in range(1, len(schemas)):
                schema = schemas[i]
                
                # Check if current schema overlaps with the current group
                if schema.start_position <= current_group.end_position:
                    # Update the current group's end_position
                    current_group.end_position = max(current_group.end_position, schema.end_position)
                    # Aggregate the values
                    aggregated_ids.add(schema.bgc_id)
                    aggregated_accessions.add(schema.bgc_accession)
                    aggregated_detector_names.add(schema.bgc_detector_name)
                    aggregated_class_names.add(schema.bgc_class_name)
                else:
                    
                    # If not overlapping, save the current group and start a new one
                    output_schemas.append(BgcSearchOutputSchema(
                        bgc_ids=list(aggregated_ids),  # Convert set to list
                        bgc_accessions=list(aggregated_accessions),  # Convert set to list
                        assembly_accession=current_group.assembly_accession,
                        contig_mgyc=current_group.contig_mgyc,
                        start_position=current_group.start_position,
                        end_position=current_group.end_position,
                        bgc_detector_names=aggregated_detector_names,  # Set is fine as is
                        bgc_class_names=aggregated_class_names,  # Set is fine as is
                    ))

                    # Start a new group
                    current_group = schema
                    aggregated_ids = {schema.bgc_id}
                    aggregated_accessions = {schema.bgc_accession}
                    aggregated_detector_names = {schema.bgc_detector_name}
                    aggregated_class_names = {schema.bgc_class_name}
            # Don't forget to add the last group
            output_schemas.append(BgcSearchOutputSchema(
                bgc_ids=list(aggregated_ids),  # Convert set to list
                bgc_accessions=list(aggregated_accessions),  # Convert set to list
                assembly_accession=current_group.assembly_accession,
                contig_mgyc=current_group.contig_mgyc,
                start_position=current_group.start_position,
                end_position=current_group.end_position,
                bgc_detector_names=list(aggregated_detector_names),  # Set is fine as is
                bgc_class_names=list(aggregated_class_names),  # Set is fine as is
            ))

        return output_schemas
    
    @staticmethod
    def intersection(input_schemas: List[BgcSearchInputSchema], detector_names: List[str]) -> List[BgcSearchOutputSchema]:
        grouped_by_contig: Dict[str, List[BgcSearchInputSchema]] = {}
        
        # Step 1: Group by contig_mgyc
        for schema in input_schemas:
            if schema.contig_mgyc not in grouped_by_contig:
                grouped_by_contig[schema.contig_mgyc] = []
            grouped_by_contig[schema.contig_mgyc].append(schema)

        output_schemas = []

        # Step 2: Process each group for overlapping regions with all specified detector names
        for contig_mgyc, schemas in grouped_by_contig.items():
            # Sort schemas by start_position to make it easier to detect overlaps
            schemas.sort(key=lambda s: s.start_position)
            # Filter schemas by detector names
            filtered_schemas = [s for s in schemas if s.bgc_detector_name in detector_names]

            if not filtered_schemas or len(filtered_schemas) < len(detector_names):
                continue

            current_group = filtered_schemas[0]
            aggregated_ids = {current_group.bgc_id}
            aggregated_accessions = {current_group.bgc_accession}
            aggregated_detector_names = {current_group.bgc_detector_name}
            aggregated_class_names = {current_group.bgc_class_name}

            for i in range(1, len(filtered_schemas)):
                schema = filtered_schemas[i]
                
                # Check if the current schema overlaps with the current group and has all detector names
                if schema.start_position <= current_group.end_position and all(name in detector_names for name in aggregated_detector_names):
                    # Update the current group's end_position to the intersection
                    current_group.end_position = min(current_group.end_position, schema.end_position)
                    current_group.start_position = max(current_group.start_position, schema.start_position)
                    # Aggregate the values
                    aggregated_ids.add(schema.bgc_id)
                    aggregated_accessions.add(schema.bgc_accession)
                    aggregated_detector_names.add(schema.bgc_detector_name)
                    aggregated_class_names.add(schema.bgc_class_name)
                else:
                    # If not overlapping, start a new group, or if it doesn't match all detector names, skip
                    if len(aggregated_detector_names) == len(detector_names):
                        output_schemas.append(BgcSearchOutputSchema(
                            bgc_ids=list(aggregated_ids),
                            bgc_accessions=list(aggregated_accessions),
                            assembly_accession=current_group.assembly_accession,
                            contig_mgyc=current_group.contig_mgyc,
                            start_position=current_group.start_position,
                            end_position=current_group.end_position,
                            bgc_detector_names=list(aggregated_detector_names),
                            bgc_class_names=list(aggregated_class_names),
                        ))

                    current_group = schema
                    aggregated_ids = {schema.bgc_id}
                    aggregated_accessions = {schema.bgc_accession}
                    aggregated_detector_names = {schema.bgc_detector_name}
                    aggregated_class_names = {schema.bgc_class_name}

            # Don't forget to add the last group if it meets the criteria
            if len(aggregated_detector_names) == len(detector_names):
                output_schemas.append(BgcSearchOutputSchema(
                    bgc_ids=list(aggregated_ids),
                    bgc_accessions=list(aggregated_accessions),
                    assembly_accession=current_group.assembly_accession,
                    contig_mgyc=current_group.contig_mgyc,
                    start_position=current_group.start_position,
                    end_position=current_group.end_position,
                    bgc_detector_names=list(aggregated_detector_names),
                    bgc_class_names=list(aggregated_class_names),
                ))

        return output_schemas